from pathlib import Path

import cv2


root = Path(__file__).resolve().parents[1]
source = root / "assets/rift-illustration-source-v1.png"
model = root / "models/FSRCNN_x4.pb"
output = root / "assets/rift-illustration-4k.png"

image = cv2.imread(str(source), cv2.IMREAD_COLOR)
if image is None:
    raise SystemExit(f"could not read {source}")

sr = cv2.dnn_superres.DnnSuperResImpl_create()
sr.readModel(str(model))
sr.setModel("fsrcnn", 4)
upscaled = sr.upsample(image)
target = cv2.resize(upscaled, (3840, 2160), interpolation=cv2.INTER_LANCZOS4)
cv2.imwrite(str(output), target, [cv2.IMWRITE_PNG_COMPRESSION, 3])
print(output)
print(target.shape[1], target.shape[0])
