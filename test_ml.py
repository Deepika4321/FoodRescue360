

from backend.ml_model import MODEL_METRICS

print("MODEL EVALUATION")

for key, value in MODEL_METRICS.items():
    print(f"{key}: {value}")
