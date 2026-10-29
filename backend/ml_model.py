
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    r2_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# Dataset path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "Food_Delivery_Times.csv"

TARGET = "Delivery_Time_min"

NUMERIC_FEATURES = [
    "Distance_km",
    "Preparation_Time_min",
    "Courier_Experience_yrs",
]

CATEGORICAL_FEATURES = [
    "Weather",
    "Traffic_Level",
    "Time_of_Day",
    "Vehicle_Type",
]

# Demonstration threshold for classification
TIME_THRESHOLD = 20


def train_delivery_model():

    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATA_PATH}. "
            "Place Food_Delivery_Times.csv inside the data folder."
        )

    df = pd.read_csv(DATA_PATH)

    required_columns = (
        NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET]
    )

    missing_columns = [
        c for c in required_columns if c not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Dataset is missing columns: {missing_columns}"
        )

    # Convert numeric values safely
    for col in NUMERIC_FEATURES + [TARGET]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove rows where target value is missing
    df = df.dropna(subset=[TARGET]).copy()

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = df[TARGET]

    # Preprocessing for numeric features
    numeric_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
    ])

    # Preprocessing for categorical features
    categorical_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OneHotEncoder(handle_unknown="ignore")),
    ])

    preprocessing = ColumnTransformer([
        ("numeric", numeric_pipeline, NUMERIC_FEATURES),
        ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
    ])

    # Random Forest regression model
    model = Pipeline([
        ("preprocessing", preprocessing),
        ("regressor", RandomForestRegressor(
            n_estimators=200,
            random_state=42,
            min_samples_leaf=2,
            n_jobs=-1,
        )),
    ])

    # Split dataset: 80% training and 20% testing
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
    )

    # Train model and predict delivery time
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    # ---------------------------------
    # 1. REGRESSION EVALUATION
    # ---------------------------------

    r2 = r2_score(y_test, predictions)
    mae = mean_absolute_error(y_test, predictions)

    # ---------------------------------
    # 2. CLASSIFICATION EVALUATION
    # ---------------------------------
    # 1 = delivery time greater than 20 minutes
    # 0 = delivery time 20 minutes or less

    actual_classes = (y_test > TIME_THRESHOLD).astype(int)

    predicted_classes = (
        predictions > TIME_THRESHOLD
    ).astype(int)

    accuracy = accuracy_score(
        actual_classes, predicted_classes
    )

    precision = precision_score(
        actual_classes,
        predicted_classes,
        zero_division=0,
    )

    recall = recall_score(
        actual_classes,
        predicted_classes,
        zero_division=0,
    )

    f1 = f1_score(
        actual_classes,
        predicted_classes,
        zero_division=0,
    )

    # Confusion matrix: rows = actual, columns = predicted
    cm = confusion_matrix(
        actual_classes,
        predicted_classes,
        labels=[0, 1],
    )

    # ---------------------------------
    # 3. STORE ALL EVALUATION RESULTS
    # ---------------------------------

    metrics = {
        "dataset": DATA_PATH.name,
        "total_rows": int(len(df)),
        "training_rows": int(len(X_train)),
        "testing_rows": int(len(X_test)),
        "model": "Random Forest Regressor",
        "target": TARGET,

        # Regression metrics
        "r2_score": round(float(r2), 4),
        "mae_minutes": round(float(mae), 2),

        # Threshold-based classification metrics
        "accuracy": round(float(accuracy), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1_score": round(float(f1), 4),

        # Additional verification information
        "classification_threshold_minutes": TIME_THRESHOLD,
        "actual_class_counts": {
        str(int(k)): int(v)
        for k, v in pd.Series(actual_classes).value_counts().items()
        },
        "predicted_class_counts": {
        str(int(k)): int(v)
        for k, v in pd.Series(predicted_classes).value_counts().items()
        },
        "confusion_matrix": cm.tolist(),

        "missing_values_handled": True,
        "data_source": DATA_PATH.name,
    }

    return model, metrics


# Train the model when this module is imported
delivery_model, MODEL_METRICS = train_delivery_model()


def predict_delivery_time(
    distance_km,
    weather,
    traffic_level,
    time_of_day,
    vehicle_type,
    preparation_time_min,
    courier_experience_yrs,
):

    input_data = pd.DataFrame([{
        "Distance_km": distance_km,
        "Weather": weather,
        "Traffic_Level": traffic_level,
        "Time_of_Day": time_of_day,
        "Vehicle_Type": vehicle_type,
        "Preparation_Time_min": preparation_time_min,
        "Courier_Experience_yrs": courier_experience_yrs,
    }])

    predicted_minutes = float(
        delivery_model.predict(input_data)[0]
    )

    return {
        "predicted_delivery_time_minutes": round(
            max(0, predicted_minutes), 2
        ),
        "model": "Random Forest Regressor",
        "data_source": DATA_PATH.name,
    }
