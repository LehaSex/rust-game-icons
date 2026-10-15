
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import numpy as np
    import torch
    from PIL import Image
except ImportError as exc:
    sys.exit(f"Missing dependency: {exc}. Run: pip install torch spandrel pillow numpy")


DEFAULT_MODEL = "RealESRGAN_x4plus.pth"
MODEL_URLS = {
    DEFAULT_MODEL: "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
}


def device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def ensure_model(path: Path) -> Path:
    if path.is_file():
        return path
    url = MODEL_URLS.get(path.name)
    if not url:
        sys.exit(
            f"Model not found: {path}\n"
            f"Place {DEFAULT_MODEL} in models/, or pass --model <file>. "
            f"It can be fetched from {url if path.name == DEFAULT_MODEL else MODEL_URLS[DEFAULT_MODEL]}"
        )
    import urllib.request

    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        sys.exit(f"downloaded model is suspiciously small; refusing to use {url}")
    tmp.replace(path)
    return path


def load_model(path: Path, dev: str, half: bool):
    from spandrel import ImageModelDescriptor, ModelLoader

    desc = ModelLoader().load_from_file(str(path))
    if not isinstance(desc, ImageModelDescriptor):
        sys.exit(f"Not an SR model: {path} (purpose={desc.purpose})")
    model = desc.to(dev).eval()
    if half and dev == "cuda":
        model = model.half()
    print(f"model: {desc.architecture.id}, scale {desc.scale}, half={half and dev == 'cuda'}")
    return model, desc.scale


def to_tensor(rgb: np.ndarray, dev: str, half: bool) -> "torch.Tensor":
    arr = np.ascontiguousarray(rgb.transpose(2, 0, 1)).astype(np.float32) / 255.0
    t = torch.from_numpy(arr).unsqueeze(0).to(dev)
    return t.half() if half else t


def upscale_tensor(model, tensor, scale: int, tile: int, tile_pad: int, half: bool):
    if tile <= 0 or (tensor.shape[-1] <= tile and tensor.shape[-2] <= tile):
        with torch.no_grad():
            return model(tensor)

    _, _, h, w = tensor.shape
    out = torch.zeros((1, 3, h * scale, w * scale), dtype=tensor.dtype, device=tensor.device)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0 = y, x
            y1, x1 = min(y + tile, h), min(x + tile, w)
            py0, px0 = max(y0 - tile_pad, 0), max(x0 - tile_pad, 0)
            py1, px1 = min(y1 + tile_pad, h), min(x1 + tile_pad, w)
            patch = tensor[:, :, py0:py1, px0:px1]
            with torch.no_grad():
                res = model(patch)
            oy, ox = (y0 - py0) * scale, (x0 - px0) * scale
            out[:, :, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = res[
                :, :, oy:oy + (y1 - y0) * scale, ox:ox + (x1 - x0) * scale
            ]
            del res, patch
    return out


def upscale_one(model, scale: int, src: Path, dst: Path, dev: str, tile: int,
                tile_pad: int, half: bool) -> None:
    with Image.open(src) as img:
        rgb = img.convert("RGB")
        rgb.load()
                                                                              
                                                                        
                       
    src_arr = np.asarray(Image.open(src).convert("RGBA"), dtype=np.float32)
    alpha = src_arr[..., 3:4] / 255.0
    rgb_arr = np.asarray(rgb, dtype=np.float32) * alpha

    tensor = to_tensor(rgb_arr, dev, half)
    result = upscale_tensor(model, tensor, scale, tile, tile_pad, half)
    del tensor
    out = result.squeeze(0).permute(1, 2, 0).float().cpu().numpy()
    del result
    if half:
        out = out * 255.0
    else:
        out = (out * 255.0).clip(0, 255)
    np.clip(out, 0, 255, out=out)

    upscaled = Image.fromarray(out.astype(np.uint8), "RGB")
                                                                                           
    rgb_final = np.asarray(
        upscaled.resize((1080, 1080), Image.Resampling.LANCZOS), dtype=np.float32
    )
    a_final = np.asarray(
        Image.open(src).convert("RGBA").resize((1080, 1080), Image.Resampling.LANCZOS),
        dtype=np.float32,
    )[..., 3:4]
    rgb_out = np.where(a_final >= 8, np.clip(rgb_final * 255.0 / np.maximum(a_final, 8.0), 0, 255), 0)
    Image.fromarray(
        np.concatenate([rgb_out.astype(np.uint8), a_final.astype(np.uint8)], axis=-1), "RGBA"
    ).save(dst, optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI icon upscaling on torch (replaces upscayl)")
    ap.add_argument("--in-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--tile", type=int, default=int(os.environ.get("TILE", "512")))
    ap.add_argument("--tile-pad", type=int, default=32)
    ap.add_argument("--fp32", action="store_true", help="fp32 instead of fp16")
    args = ap.parse_args()

    dev = device()
    half = dev == "cuda" and not args.fp32
    torch.backends.cudnn.benchmark = True

    model_path = ensure_model(args.model)
    model, scale = load_model(model_path, dev, half)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(args.in_dir.glob("*.png"))
    if not files:
        print("no *.png in the input folder, nothing to do")
        return 0

    print(f"device {dev}, {len(files)} files")
    for i, src in enumerate(files, 1):
        dst = args.out_dir / src.name
        upscale_one(model, scale, src, dst, dev, args.tile, args.tile_pad, half)
        print(f"  [{i}/{len(files)}] {src.name}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())