"""
LoRA Fine-Tuning Pipeline for Chatterbox / T3 Speech Language Model.
Includes offline feature extraction, PEFT LoRA training, and standalone safetensors weight merging.
"""

import csv
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch
import torch.nn as nn
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from safetensors.torch import save_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LoRATrainer")


class LoRATrainingConfig:
    def __init__(
        self,
        dataset_dir: str = "data/finetune_dataset",
        cache_dir: str = "data/finetune_cache",
        output_dir: str = "data/models/lora_checkpoint",
        merged_output_path: str = "data/models/t3_finetuned.safetensors",
        lora_r: int = 128,
        lora_alpha: int = 256,
        lora_dropout: float = 0.05,
        learning_rate: float = 1e-4,
        batch_size: int = 4,
        grad_accum_steps: int = 4,
        num_epochs: int = 5,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
    ):
        self.dataset_dir = Path(dataset_dir)
        self.cache_dir = Path(cache_dir)
        self.output_dir = Path(output_dir)
        self.merged_output_path = Path(merged_output_path)
        self.lora_r = lora_r
        self.lora_alpha = lora_alpha
        self.lora_dropout = lora_dropout
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.grad_accum_steps = grad_accum_steps
        self.num_epochs = num_epochs
        self.device = torch.device(device)


def build_t3_lora_model(t3_model: nn.Module, cfg: LoRATrainingConfig):
    """
    Configures PEFT LoRA on T3 transformer and speaker encoder.
    Freezes base backbone weights to prevent catastrophic forgetting and static noise artifacts.
    """
    # Freeze all base parameters
    for param in t3_model.parameters():
        param.requires_grad = False

    target_modules = [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj", "spkr_enc"
    ]
    modules_to_save = ["text_emb", "text_head"]

    peft_config = LoraConfig(
        r=cfg.lora_r,
        lora_alpha=cfg.lora_alpha,
        target_modules=target_modules,
        lora_dropout=cfg.lora_dropout,
        bias="none",
        modules_to_save=modules_to_save,
    )

    lora_model = get_peft_model(t3_model, peft_config)
    trainable_params = sum(p.numel() for p in lora_model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in lora_model.parameters())
    logger.info(
        f"LoRA Injected: {trainable_params:,} trainable / {total_params:,} total parameters "
        f"({trainable_params / total_params * 100:.2f}%)"
    )
    return lora_model


def preprocess_offline_dataset(cfg: LoRATrainingConfig, base_tts_model) -> list[dict]:
    """
    Pre-extracts speaker embeddings, acoustic speech tokens, and text tokens to disk.
    Prevents CPU-bound bottlenecks during gradient steps.
    """
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = cfg.dataset_dir / "metadata.csv"
    wavs_dir = cfg.dataset_dir / "wavs"

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing {metadata_path}. Please curate dataset first.")

    cached_samples = []
    with open(metadata_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="|")
        for row in reader:
            if len(row) < 2:
                continue
            clip_id, text = row[0], row[1]
            wav_path = wavs_dir / f"{clip_id}.wav"
            if not wav_path.exists():
                continue

            cache_file = cfg.cache_dir / f"{clip_id}.pt"
            if cache_file.exists():
                cached_samples.append(str(cache_file))
                continue

            # Process audio through Chatterbox internals
            import librosa
            s3gen_wav, _ = librosa.load(str(wav_path), sr=24000)
            ref_16k = librosa.resample(s3gen_wav, orig_sr=24000, target_sr=16000)

            # Speaker embedding
            spkr_emb_np = base_tts_model.ve.embeds_from_wavs([ref_16k], sample_rate=16000)
            spkr_emb = torch.from_numpy(spkr_emb_np).float()

            # Speech tokens
            ref_16k_tensor = torch.from_numpy(ref_16k).float().unsqueeze(0)
            with torch.inference_mode():
                speech_tokens, _ = base_tts_model.s3gen.tokenizer.forward(ref_16k_tensor)

            # Text tokens
            text_tokens = base_tts_model.tokenizer.text_to_tokens(text, language_id="en")

            sample_data = {
                "id": clip_id,
                "text": text,
                "spkr_emb": spkr_emb,
                "speech_tokens": speech_tokens,
                "text_tokens": text_tokens,
            }
            torch.save(sample_data, cache_file)
            cached_samples.append(str(cache_file))

    logger.info(f"Offline Preprocessing complete: {len(cached_samples)} samples cached in {cfg.cache_dir}")
    return cached_samples


def merge_lora_and_export_safetensors(lora_model, output_path: str):
    """
    Merges PEFT LoRA adapter weights directly into the base T3 model and saves a standalone safetensors file.
    Produces a zero-overhead model that runs at full speed on CPU without PEFT dependencies.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Merging LoRA weights into standalone safetensors...")
    base_merged = lora_model.merge_and_unload()
    state_dict = base_merged.state_dict()

    # Save cleanly as safetensors
    save_file(state_dict, str(out_file))
    logger.info(f"Standalone model exported successfully: {out_file} ({out_file.stat().st_size / (1024*1024):.1f} MB)")
    return str(out_file)


def run_lora_training(cfg: Optional[LoRATrainingConfig] = None):
    """
    Executes the full end-to-end LoRA training loop and exports the merged safetensors model.
    """
    if cfg is None:
        cfg = LoRATrainingConfig()

    import os
    import time
    from torch.optim import AdamW
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from app.core.tts_engine import TTSEngine

    optimal_threads = min(8, os.cpu_count() or 6)
    torch.set_num_threads(optimal_threads)

    logger.info("Initializing TTS Engine and base T3 model...")
    engine = TTSEngine.get_instance()
    base_tts = engine.load_model()

    # Ensure preprocessed dataset exists
    cached_paths = [str(p) for p in cfg.cache_dir.glob("*.pt")]
    if not cached_paths:
        logger.info("Cache empty. Running offline preprocessing...")
        cached_paths = preprocess_offline_dataset(cfg, base_tts)

    logger.info(f"Loaded {len(cached_paths)} cached speech samples for training.")

    # Configure LoRA on T3
    lora_model = build_t3_lora_model(base_tts.t3, cfg)
    lora_model.train()

    optimizer = AdamW(
        [p for p in lora_model.parameters() if p.requires_grad],
        lr=cfg.learning_rate,
        weight_decay=0.01,
    )

    sot = base_tts.t3.hp.start_text_token
    eot = base_tts.t3.hp.stop_text_token
    emotion_tensor = torch.tensor([[[0.5]]])

    logger.info(f"Starting training run: {cfg.num_epochs} epochs, lr={cfg.learning_rate}...")

    total_steps = 0
    start_time = time.time()

    for epoch in range(1, cfg.num_epochs + 1):
        epoch_loss = 0.0
        step_count = 0

        for sample_path in cached_paths:
            sample = torch.load(sample_path)
            spkr_emb = sample["spkr_emb"]
            speech_toks = sample["speech_tokens"]
            text_toks = sample["text_tokens"]

            # Pad text tokens with start and end tokens
            text_toks_padded = F.pad(text_toks, (1, 0), value=sot)
            text_toks_padded = F.pad(text_toks_padded, (0, 1), value=eot)

            t3_cond = T3Cond(speaker_emb=spkr_emb, emotion_adv=emotion_tensor)
            text_lens = torch.tensor([text_toks_padded.size(1)], dtype=torch.long)
            speech_lens = torch.tensor([speech_toks.size(1)], dtype=torch.long)

            out = lora_model(
                t3_cond=t3_cond,
                text_tokens=text_toks_padded,
                text_token_lens=text_lens,
                speech_tokens=speech_toks,
                speech_token_lens=speech_lens,
                training=True,
            )

            speech_vocab_size = out.speech_logits.size(-1)
            loss = F.cross_entropy(out.speech_logits.view(-1, speech_vocab_size), speech_toks.view(-1))

            loss = loss / cfg.grad_accum_steps
            loss.backward()

            step_count += 1
            total_steps += 1
            epoch_loss += loss.item() * cfg.grad_accum_steps

            if step_count % cfg.grad_accum_steps == 0:
                torch.nn.utils.clip_grad_norm_(lora_model.parameters(), max_norm=1.0)
                optimizer.step()
                optimizer.zero_grad()

        # Flush any remaining gradients
        if step_count % cfg.grad_accum_steps != 0:
            torch.nn.utils.clip_grad_norm_(lora_model.parameters(), max_norm=1.0)
            optimizer.step()
            optimizer.zero_grad()

        avg_loss = epoch_loss / max(1, step_count)
        logger.info(f"Epoch [{epoch}/{cfg.num_epochs}] completed - Loss: {avg_loss:.4f} (elapsed: {time.time() - start_time:.1f}s)")

    logger.info("Training loop completed successfully. Saving LoRA adapter checkpoint...")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    lora_model.save_pretrained(str(cfg.output_dir))

    # Merge into standalone safetensors file
    merged_path = merge_lora_and_export_safetensors(lora_model, str(cfg.merged_output_path))
    logger.info(f"All done! Merged model ready at {merged_path}")
    return merged_path


if __name__ == "__main__":
    run_lora_training()
