from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pymongo import GEOSPHERE

from database import db
from backend.ml_model import MODEL_METRICS, predict_delivery_time


app = FastAPI(
    title="FoodRescue360 API",
    description="Smart Food Redistribution and Donation Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB collections using PyMongo
food_collection = db["food_listings"]
ngo_collection = db["ngos"]
delivery_data_collection = db["delivery_training_data"]

# Geospatial index for nearby NGO search
ngo_collection.create_index([("location", GEOSPHERE)])


# -------------------- MODELS --------------------
class FoodListing(BaseModel):
    food_name: str = Field(min_length=2)
    quantity: float = Field(gt=0)
    unit: str = "kg"
    donor_name: str = Field(min_length=2)
    location: str = Field(min_length=2)
    expires_at: datetime


class NGORegistration(BaseModel):
    name: str = Field(min_length=2)
    contact_person: str = Field(min_length=2)
    phone: str = Field(min_length=10)
    address: str = Field(min_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    required_quantity: float = Field(gt=0)


class FoodClaimRequest(BaseModel):
    ngo_id: str


class DeliveryPredictionRequest(BaseModel):
    distance_km: float = Field(gt=0)
    weather: str
    traffic_level: str
    time_of_day: str
    vehicle_type: str
    preparation_time_min: float = Field(ge=0)
    courier_experience_yrs: float = Field(ge=0)


# -------------------- HELPERS --------------------
def serialize_document(document):
    """Convert MongoDB ObjectId and datetime values into JSON-safe values."""
    document = dict(document)
    if "_id" in document:
        document["_id"] = str(document["_id"])

    for field, value in document.items():
        if isinstance(value, datetime):
            document[field] = value.isoformat()
    return document


def parse_object_id(value: str, label: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} ID.")


# -------------------- HOME --------------------
@app.get("/")
def home():
    return {
        "message": "Welcome to FoodRescue360!",
        "database": "MongoDB with PyMongo",
        "features": [
            "Food donation listings",
            "Expiry-aware prioritization",
            "Available food search",
            "Food listing by ID",
            "NGO registration and verification",
            "Verified NGO food claiming",
            "Nearby NGO search",
            "Claimed food tracking",
            "ML delivery-time prediction",
        ],
    }


# -------------------- ADD FOOD --------------------
@app.post("/food", status_code=201)
def add_food(item: FoodListing):
    now = datetime.now(timezone.utc)
    expiry = item.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    else:
        expiry = expiry.astimezone(timezone.utc)

    if expiry <= now:
        raise HTTPException(
            status_code=400,
            detail="Cannot add food that has already expired.",
        )

    food = item.model_dump()
    food["expires_at"] = expiry
    food["created_at"] = now
    food["status"] = "available"

    try:
        result = food_collection.insert_one(food)
        food["_id"] = result.inserted_id
        return {
            "message": "Food listing added successfully!",
            "food": serialize_document(food),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unable to save food listing.",
        ) from e


# -------------------- GET AVAILABLE FOOD --------------------
@app.get("/food")
def get_food():
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=6)
    try:
        food_collection.update_many(
            {"expires_at": {"$lte": now}, "status": "available"},
            {"$set": {"status": "expired"}},
        )
        listings = food_collection.find({"status": "available"}).sort("expires_at", 1)
        result = []
        for food in listings:
            expiry = food["expires_at"]
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            food["priority"] = "urgent" if expiry <= deadline else "normal"
            result.append(serialize_document(food))
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve food listings.",
        ) from e


# -------------------- CLAIMED FOOD (keep before /food/{food_id}) --------------------
@app.get("/food/claimed")
def get_claimed_food():
    foods = food_collection.find(
        {"status": {"$in": ["claimed", "collected"]}}
    ).sort("claimed_at", -1)
    return [serialize_document(food) for food in foods]


# -------------------- CLAIM FOOD AS A VERIFIED NGO --------------------
@app.post("/food/{food_id}/claim")
def claim_food(food_id: str, request: FoodClaimRequest):
    food_object_id = parse_object_id(food_id, "food")
    ngo_object_id = parse_object_id(request.ngo_id, "NGO")

    ngo = ngo_collection.find_one({"_id": ngo_object_id, "verified": True})
    if ngo is None:
        raise HTTPException(
            status_code=403,
            detail="Only registered and verified NGOs can claim food.",
        )

    now = datetime.now(timezone.utc)
    food = food_collection.find_one({"_id": food_object_id})
    if food is None:
        raise HTTPException(status_code=404, detail="Food listing not found.")

    expiry = food.get("expires_at")
    if expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            food_collection.update_one(
                {"_id": food_object_id, "status": "available"},
                {"$set": {"status": "expired"}},
            )
            raise HTTPException(status_code=400, detail="Expired food cannot be claimed.")

    # Atomic conditional update prevents two NGOs claiming the same listing.
    result = food_collection.update_one(
        {
            "_id": food_object_id,
            "status": "available",
            "expires_at": {"$gt": now},
        },
        {
            "$set": {
                "status": "claimed",
                "claimed_by_ngo_id": str(ngo["_id"]),
                "claimed_by_ngo_name": ngo["name"],
                "claimed_by_ngo_contact": ngo["contact_person"],
                "claimed_by_ngo_phone": ngo["phone"],
                "claimed_at": now,
            }
        },
    )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Food is no longer available to claim.",
        )

    return {
        "message": "Food claimed successfully.",
        "food_id": food_id,
        "claimed_by_ngo": ngo["name"],
        "contact_person": ngo["contact_person"],
        "phone": ngo["phone"],
        "status": "claimed",
    }


# -------------------- GET FOOD BY ID --------------------
@app.get("/food/{food_id}")
def get_food_by_id(food_id: str):
    object_id = parse_object_id(food_id, "food listing")
    food = food_collection.find_one({"_id": object_id})
    if food is None:
        raise HTTPException(status_code=404, detail="Food listing not found.")
    return serialize_document(food)


# -------------------- REGISTER NGO --------------------
@app.post("/ngos", status_code=201)
def register_ngo(ngo: NGORegistration):
    ngo_data = ngo.model_dump()
    latitude = ngo_data.pop("latitude")
    longitude = ngo_data.pop("longitude")
    ngo_data["location"] = {
        "type": "Point",
        "coordinates": [longitude, latitude],
    }
    ngo_data["verified"] = False
    ngo_data["created_at"] = datetime.now(timezone.utc)

    try:
        result = ngo_collection.insert_one(ngo_data)
        ngo_data["_id"] = result.inserted_id
        return {
            "message": "NGO registered successfully!",
            "verification_status": "pending",
            "ngo": serialize_document(ngo_data),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unable to register NGO.",
        ) from e


# -------------------- VERIFY NGO (DEMO ADMIN ENDPOINT) --------------------
@app.patch("/ngos/{ngo_id}/verify")
def verify_ngo(ngo_id: str):
    """Demo-only verification endpoint; protect with admin authentication in production."""
    object_id = parse_object_id(ngo_id, "NGO")
    result = ngo_collection.update_one(
        {"_id": object_id},
        {"$set": {"verified": True}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="NGO not found.")
    return {"message": "NGO verified successfully.", "ngo_id": ngo_id, "verified": True}


# -------------------- LIST VERIFIED NGOs FOR CLAIMING --------------------
@app.get("/ngos/verified")
def get_verified_ngos():
    ngos = ngo_collection.find({"verified": True}).sort("name", 1)
    return [
        {
            "id": str(ngo["_id"]),
            "name": ngo["name"],
            "contact_person": ngo["contact_person"],
            "phone": ngo["phone"],
            "address": ngo["address"],
            "verified": True,
        }
        for ngo in ngos
    ]


# -------------------- FIND NEARBY NGOs --------------------
@app.get("/ngos/nearby")
def find_nearby_ngos(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    max_distance_km: float = Query(20, gt=0, le=100),
    quantity: float = Query(1, gt=0),
):
    try:
        nearby = ngo_collection.find(
            {
                "location": {
                    "$near": {
                        "$geometry": {
                            "type": "Point",
                            "coordinates": [longitude, latitude],
                        },
                        "$maxDistance": max_distance_km * 1000,
                    }
                },
                "required_quantity": {"$lte": quantity},
            }
        )
        results = []
        for ngo in nearby:
            coordinates = ngo["location"]["coordinates"]
            results.append(
                {
                    "id": str(ngo["_id"]),
                    "name": ngo["name"],
                    "contact_person": ngo["contact_person"],
                    "phone": ngo["phone"],
                    "address": ngo["address"],
                    "required_quantity": ngo["required_quantity"],
                    "verified": ngo.get("verified", False),
                    "coordinates": {
                        "longitude": coordinates[0],
                        "latitude": coordinates[1],
                    },
                }
            )
        return {"count": len(results), "radius_km": max_distance_km, "ngos": results}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unable to find nearby NGOs.",
        ) from e


# -------------------- UPDATE FOOD STATUS --------------------
@app.patch("/food/{food_id}/status")
def update_food_status(food_id: str, status: str = Query(...)):
    # Claiming must go through /food/{food_id}/claim with a verified NGO ID.
    if status == "claimed":
        raise HTTPException(
            status_code=400,
            detail="Use POST /food/{food_id}/claim and provide a verified ngo_id.",
        )
    if status not in ["available", "collected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be available or collected. Claim through the NGO claim endpoint.",
        )

    object_id = parse_object_id(food_id, "food listing")
    food = food_collection.find_one({"_id": object_id})
    if food is None:
        raise HTTPException(status_code=404, detail="Food listing not found.")
    if food.get("status") == "expired":
        raise HTTPException(status_code=400, detail="Expired food cannot be updated.")
    if status == "available":
        raise HTTPException(
            status_code=400,
            detail="Food cannot be reopened using this endpoint.",
        )
    if food.get("status") != "claimed":
        raise HTTPException(
            status_code=400,
            detail="Only claimed food can be marked as collected.",
        )

    now = datetime.now(timezone.utc)
    result = food_collection.update_one(
        {"_id": object_id, "status": "claimed"},
        {"$set": {"status": "collected", "collected_at": now}},
    )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Food status changed. Refresh and try again.",
        )
    return {
        "message": "Food marked as collected.",
        "food_id": food_id,
        "status": "collected",
        "collected_at": now.isoformat(),
    }


# -------------------- DASHBOARD STATS --------------------
@app.get("/dashboard/stats")
def dashboard_stats():
    now = datetime.now(timezone.utc)
    food_collection.update_many(
        {"expires_at": {"$lte": now}, "status": "available"},
        {"$set": {"status": "expired"}},
    )
    return {
        "total_food_listings": food_collection.count_documents({}),
        "available_food": food_collection.count_documents({"status": "available"}),
        "claimed_food": food_collection.count_documents({"status": "claimed"}),
        "collected_food": food_collection.count_documents({"status": "collected"}),
        "expired_food": food_collection.count_documents({"status": "expired"}),
        "total_ngos": ngo_collection.count_documents({}),
        "verified_ngos": ngo_collection.count_documents({"verified": True}),
    }


# -------------------- ML DELIVERY PREDICTION --------------------
@app.get("/ml/metrics")
def get_model_metrics():
    """Return evaluation results from the CSV test split."""
    return MODEL_METRICS


@app.post("/ml/import-dataset")
def import_delivery_dataset():
    """Import CSV rows into a separate MongoDB collection."""
    csv_path = Path(__file__).resolve().parent.parent / "data" / "Food_Delivery_Times.csv"
    if not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Food_Delivery_Times.csv was not found in the data folder.",
        )

    try:
        df = pd.read_csv(csv_path)
        df = df.astype(object).where(pd.notna(df), None)
        records = df.to_dict(orient="records")
        if not records:
            raise HTTPException(status_code=400, detail="The CSV dataset is empty.")

        for record in records:
            order_id = record.get("Order_ID")
            if order_id is None:
                continue
            delivery_data_collection.update_one(
                {"Order_ID": order_id},
                {"$set": record},
                upsert=True,
            )

        return {
            "message": "Dataset imported into MongoDB successfully.",
            "csv_rows": len(records),
            "mongodb_collection": "delivery_training_data",
            "mongodb_documents": delivery_data_collection.count_documents({}),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Dataset import failed. Check the backend terminal.",
        ) from e


@app.post("/ml/predict")
def predict_delivery(request: DeliveryPredictionRequest):
    """Predict delivery duration in minutes; not a food-rescue pickup guarantee."""
    try:
        prediction = predict_delivery_time(
            distance_km=request.distance_km,
            weather=request.weather,
            traffic_level=request.traffic_level,
            time_of_day=request.time_of_day,
            vehicle_type=request.vehicle_type,
            preparation_time_min=request.preparation_time_min,
            courier_experience_yrs=request.courier_experience_yrs,
        )
        return {
            "prediction": prediction,
            "model_metrics": MODEL_METRICS,
            "notice": (
                "This estimates general food delivery time. "
                "It is not a validated food-rescue pickup-time guarantee."
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Delivery prediction failed.") from e
