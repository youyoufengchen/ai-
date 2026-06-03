"""
HMR2 (4DHumans) video → canonical.json 转换器

不需要 detectron2，适用于单人全身视频。
使用 HMR2.0 模型对每帧提取 SMPL 参数，再转为 canonical.json。

用法:
    python tools/hmr2_to_canonical.py --video input.mp4 --out output.canonical.json
"""

import os
import sys
import argparse
import json
import warnings
from pathlib import Path

import cv2
import numpy as np
import torch

# ---------------------------------------------------------------------------
# 把 4D-Humans 加入路径并导入
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
FOURD_HUMANS = REPO_ROOT / "tools" / "4D-Humans"
sys.path.insert(0, str(FOURD_HUMANS))

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
warnings.filterwarnings("ignore")

from hmr2.models import load_hmr2
from hmr2.datasets.utils import (
    expand_to_aspect_ratio,
    generate_image_patch_cv2,
    convert_cvimg_to_tensor,
)
from hmr2.configs import CACHE_DIR_4DHUMANS

# ---------------------------------------------------------------------------
# 导入 smpl_to_canonical 的转换函数
# ---------------------------------------------------------------------------
sys.path.insert(0, str(REPO_ROOT / "tools"))
from smpl_to_canonical import smpl_to_canonical

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_MEAN = 255.0 * np.array([0.485, 0.456, 0.406])
DEFAULT_STD = 255.0 * np.array([0.229, 0.224, 0.225])


def preprocess_frame(img_cv2: np.ndarray, cfg, bbox: np.ndarray = None) -> dict:
    """
    将 OpenCV 图像裁剪、缩放为 HMR2 模型输入。

    Args:
        img_cv2: (H, W, 3) BGR 图像
        cfg: HMR2 模型配置
        bbox: (4,) [x1, y1, x2, y2]，None 时使用整帧

    Returns:
        item: dict 包含 'img', 'box_center', 'box_size', 'img_size'
    """
    h, w = img_cv2.shape[:2]
    if bbox is None:
        bbox = np.array([0.0, 0.0, float(w), float(h)])

    bbox = bbox.astype(np.float32)
    center = (bbox[2:4] + bbox[0:2]) / 2.0
    scale_wh = bbox[2:4] - bbox[0:2]
    scale = scale_wh / 200.0

    # 扩展到目标宽高比（ViT 默认 [192,256]）
    bbox_shape = cfg.MODEL.get("BBOX_SHAPE", None)
    if bbox_shape is not None:
        bbox_size = expand_to_aspect_ratio(scale_wh, target_aspect_ratio=bbox_shape).max()
    else:
        bbox_size = max(scale_wh)

    patch_width = patch_height = cfg.MODEL.IMAGE_SIZE  # 224 或 256

    # 生成 image patch（无翻转、无旋转、缩放 1.0）
    img_patch_cv, _ = generate_image_patch_cv2(
        img_cv2,
        center[0], center[1],
        bbox_size, bbox_size,
        patch_width, patch_height,
        do_flip=False, scale=1.0, rot=0.0,
        border_mode=cv2.BORDER_CONSTANT,
    )
    # BGR → RGB
    img_patch_cv = img_patch_cv[:, :, ::-1]
    img_patch = convert_cvimg_to_tensor(img_patch_cv)

    # 归一化
    for c in range(3):
        img_patch[c] = (img_patch[c] - DEFAULT_MEAN[c]) / DEFAULT_STD[c]

    return {
        "img": torch.from_numpy(img_patch).float().unsqueeze(0),  # (1, 3, H, W)
        "box_center": center.copy(),
        "box_size": bbox_size,
        "img_size": np.array([w, h], dtype=np.float32),
    }


def extract_smpl_from_video(video_path: str, model, cfg, device: str = "cpu", max_frames: int = None) -> dict:
    """
    对视频逐帧运行 HMR2，收集 SMPL 参数。

    Returns:
        dict with keys: global_orient, body_pose, betas, pred_cam, pred_cam_t
          each is np.ndarray of shape [T, ...]
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    results = {
        "global_orient": [],
        "body_pose": [],
        "betas": [],
        "pred_cam": [],
        "pred_cam_t": [],
        "fps": fps,
    }

    model = model.to(device)
    model.eval()

    frame_idx = 0
    with torch.no_grad():
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            item = preprocess_frame(frame, cfg)
            batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in item.items()}

            out = model(batch)

            # 取出结果 (batch=1)
            smpl_params = out["pred_smpl_params"]
            results["global_orient"].append(smpl_params["global_orient"][0].cpu().numpy())
            results["body_pose"].append(smpl_params["body_pose"][0].cpu().numpy())
            results["betas"].append(smpl_params["betas"][0].cpu().numpy())
            results["pred_cam"].append(out["pred_cam"][0].cpu().numpy())
            results["pred_cam_t"].append(out["pred_cam_t"][0].cpu().numpy())

            frame_idx += 1
            if max_frames is not None and frame_idx >= max_frames:
                break
            if frame_idx % 30 == 0:
                print(f"  已处理 {frame_idx}/{frame_count} 帧")

    cap.release()

    # stack
    for k in ["global_orient", "body_pose", "betas", "pred_cam", "pred_cam_t"]:
        results[k] = np.stack(results[k], axis=0)

    print(f"共处理 {frame_idx} 帧，fps={fps:.2f}")
    return results


def build_smpl_pose_array(results: dict) -> np.ndarray:
    """
    将 HMR2 输出的旋转矩阵合并为 [T, 24, 3, 3] 数组。
    global_orient (1 joint) + body_pose (23 joints) = 24 joints
    """
    global_orient = results["global_orient"]  # [T, 1, 3, 3]
    body_pose = results["body_pose"]          # [T, 23, 3, 3]
    # 合并
    pose_rotmat = np.concatenate([global_orient, body_pose], axis=1)  # [T, 24, 3, 3]
    return pose_rotmat


def main():
    parser = argparse.ArgumentParser(description="HMR2 video → canonical.json")
    parser.add_argument("--video", required=True, help="输入视频路径")
    parser.add_argument("--out", required=True, help="输出 canonical.json 路径")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="推理设备")
    parser.add_argument("--model-path", default=None, help="SMPL .npz 模型路径（默认 data/basicModel_neutral_lbs_10_207_0_v1.0.0.npz）")
    parser.add_argument("--max-frames", type=int, default=None, help="仅处理前 N 帧（用于快速测试）")
    args = parser.parse_args()

    device = args.device if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        print("警告: CUDA 不可用，切换到 CPU")
        device = "cpu"

    print("加载 HMR2 模型...")
    model, cfg = load_hmr2()
    print("模型加载完成")

    print(f"处理视频: {args.video}")
    if args.max_frames:
        print(f"限制前 {args.max_frames} 帧（测试模式）")
    results = extract_smpl_from_video(args.video, model, cfg, device=device, max_frames=args.max_frames)

    # 构造 SMPL pose [T, 24, 3, 3]
    smpl_pose = build_smpl_pose_array(results)
    # 使用 HMR2 输出的 camera translation 作为根节点平移
    smpl_trans = results["pred_cam_t"]
    # betas 取平均（HMR2 每帧都有 betas，但通常变化不大）
    smpl_shape = results["betas"].mean(axis=0)

    print("转换为 canonical.json...")
    canonical = smpl_to_canonical(
        smpl_pose=smpl_pose,
        smpl_trans=smpl_trans,
        smpl_shape=smpl_shape,
        fps=results["fps"],
        model_path=args.model_path,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False, indent=2)

    print(f"输出已保存: {out_path}")


if __name__ == "__main__":
    main()
