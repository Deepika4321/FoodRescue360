
import { useEffect, useState, useCallback } from "react";
import {
  Heart, Utensils, MapPin, Users, Plus, RefreshCw,
  PackageCheck, Clock, CheckCircle, BarChart3, Search, BrainCircuit, Truck
} from "lucide-react";
import "./App.css";

const API = "http://127.0.0.1:8000";

const EMPTY_FOOD = {
  food_name: "",
  quantity: 10,
  unit: "kg",
  donor_name: "",
  location: "",
  expires_at: ""
};

const EMPTY_NGO = {
  name: "",
  contact_person: "",
  phone: "",
  address: "",
  latitude: 31.25,
  longitude: 75.70,
  required_quantity: 10
};

const EMPTY_SEARCH = {
  latitude: 31.25,
  longitude: 75.70,
  max_distance_km: 20,
  quantity: 15
};

const EMPTY_DELIVERY = {
  distance_km: 5,
  weather: "Clear",
  traffic_level: "Low",
  time_of_day: "Afternoon",
  vehicle_type: "Bike",
  preparation_time_min: 15,
  courier_experience_yrs: 2
};

const EMPTY_STATS = {
  total_food_listings: 0,
  available_food: 0,
  claimed_food: 0,
  collected_food: 0,
  expired_food: 0,
  total_ngos: 0,
  verified_ngos: 0
};

export default function App() {
  const [tab, setTab] = useState("food");
  const [foods, setFoods] = useState([]);
  const [ngos, setNgos] = useState([]);
  const [stats, setStats] = useState(EMPTY_STATS);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState("");

  const [food, setFood] = useState(EMPTY_FOOD);
  const [ngo, setNgo] = useState(EMPTY_NGO);
  const [search, setSearch] = useState(EMPTY_SEARCH);
  const [delivery, setDelivery] = useState(EMPTY_DELIVERY);
  const [prediction, setPrediction] = useState(null);
  const [modelMetrics, setModelMetrics] = useState(null);
  const [predicting, setPredicting] = useState(false);

  const api = useCallback(async (path, options = {}) => {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers
      }
    });

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { detail: text || "Invalid server response" };
    }

    if (!response.ok) {
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail || "Request failed")
      );
    }
    return data;
  }, []);

  function notify(text, isError = false) {
    setMessage(text);
    setError(isError);
  }

  const loadFoods = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api("/food");
      setFoods(Array.isArray(data) ? data : []);
    } catch (e) {
      notify(`Unable to load food: ${e.message}`, true);
    } finally {
      setLoading(false);
    }
  }, [api]);

  const loadStats = useCallback(async () => {
    try {
      const data = await api("/dashboard/stats");
      setStats({ ...EMPTY_STATS, ...data });
    } catch (e) {
      notify(`Unable to load statistics: ${e.message}`, true);
    }
  }, [api]);

  const refreshDashboard = useCallback(async () => {
    await Promise.all([loadFoods(), loadStats()]);
  }, [loadFoods, loadStats]);

  useEffect(() => {
    refreshDashboard();
  }, [refreshDashboard]);

  useEffect(() => {
    if (tab !== "ml") return;
    api("/ml/metrics")
      .then(setModelMetrics)
      .catch(e => notify(`Unable to load ML metrics: ${e.message}`, true));
  }, [tab, api]);

  async function predictDelivery(e) {
    e.preventDefault();
    setPredicting(true);
    setPrediction(null);
    try {
      const result = await api("/ml/predict", {
        method: "POST",
        body: JSON.stringify({
          ...delivery,
          distance_km: Number(delivery.distance_km),
          preparation_time_min: Number(delivery.preparation_time_min),
          courier_experience_yrs: Number(delivery.courier_experience_yrs)
        })
      });
      setPrediction(result);
      setModelMetrics(result.model_metrics || modelMetrics);
      notify("Delivery-time prediction generated successfully!");
    } catch (e) {
      notify(`Prediction failed: ${e.message}`, true);
    } finally {
      setPredicting(false);
    }
  }

  async function addFood(e) {
    e.preventDefault();
    try {
      if (!food.expires_at) {
        throw new Error("Please select the food expiry date and time.");
      }

      const expiry = new Date(food.expires_at);
      if (Number.isNaN(expiry.getTime()) || expiry <= new Date()) {
        throw new Error("Expiry must be a future date and time.");
      }

      await api("/food", {
        method: "POST",
        body: JSON.stringify({
          ...food,
          quantity: Number(food.quantity),
          expires_at: expiry.toISOString()
        })
      });

      notify("Food donation added successfully!");
      setFood(EMPTY_FOOD);
      await refreshDashboard();
      setTab("food");
    } catch (e) {
      notify(e.message, true);
    }
  }

  async function addNgo(e) {
    e.preventDefault();
    try {
      await api("/ngos", {
        method: "POST",
        body: JSON.stringify({
          ...ngo,
          latitude: Number(ngo.latitude),
          longitude: Number(ngo.longitude),
          required_quantity: Number(ngo.required_quantity)
        })
      });

      notify("NGO registered successfully! Verification is pending.");
      setNgo(EMPTY_NGO);
      await loadStats();
    } catch (e) {
      notify(e.message, true);
    }
  }

  async function findNgos(e) {
    e.preventDefault();
    try {
      const params = new URLSearchParams({
        latitude: String(search.latitude),
        longitude: String(search.longitude),
        max_distance_km: String(search.max_distance_km),
        quantity: String(search.quantity)
      });

      const data = await api(`/ngos/nearby?${params.toString()}`);
      setNgos(data.ngos || []);
      notify(`${data.count ?? data.ngos?.length ?? 0} nearby NGO(s) found.`);
    } catch (e) {
      setNgos([]);
      notify(e.message, true);
    }
  }

  async function updateFoodStatus(item, nextStatus) {
    try {
      setBusyId(item._id);

      if (nextStatus === "claimed") {
        // Claiming food requires a verified NGO ID; PATCH /status is not the claim route.
        let verifiedNgos = ngos.filter(n => n.verified === true);

        // If the user has not searched nearby NGOs yet, load them first.
        if (verifiedNgos.length === 0) {
          const params = new URLSearchParams({
            latitude: String(search.latitude),
            longitude: String(search.longitude),
            max_distance_km: "100",
            quantity: String(Number(item.quantity) || 1)
          });
          const result = await api(`/ngos/nearby?${params.toString()}`);
          const nearbyNgos = Array.isArray(result.ngos) ? result.ngos : [];
          setNgos(nearbyNgos);
          verifiedNgos = nearbyNgos.filter(n => n.verified === true);
        }

        if (verifiedNgos.length === 0) {
          throw new Error(
            "No verified NGO found. Open Nearby NGOs and search, or ask the project admin to verify a registered NGO."
          );
        }

        const selectedNgo = verifiedNgos[0];
        const ngoId = selectedNgo.id || selectedNgo._id;
        if (!ngoId) {
          throw new Error("Verified NGO ID is missing. Please check the NGO record.");
        }

        await api(`/food/${encodeURIComponent(item._id)}/claim`, {
          method: "POST",
          body: JSON.stringify({ ngo_id: String(ngoId) })
        });

        notify(`Food successfully claimed by ${selectedNgo.name || "the verified NGO"}!`);
      } else {
        await api(
          `/food/${encodeURIComponent(item._id)}/status?status=${encodeURIComponent(nextStatus)}`,
          { method: "PATCH" }
        );
        notify("Food marked as collected!");
      }

      await refreshDashboard();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusyId("");
    }
  }

  const field = (
    label, value, change, type = "text",
    { min, max, step, required = true } = {}
  ) => (
    <label>
      {label}
      <input
        type={type}
        value={value ?? ""}
        required={required}
        min={min}
        max={max}
        step={step}
        onChange={e => change(e.target.value)}
      />
    </label>
  );

  const navItems = [
    ["food", "Available Food", Utensils],
    ["donate", "Donate Food", Plus],
    ["register", "Register NGO", Users],
    ["nearby", "Nearby NGOs", MapPin],
    ["ml", "ML Delivery Prediction", BrainCircuit]
  ];

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <Heart size={27} />
          <h2>FoodRescue<span>360</span></h2>
        </div>

        <p className="muted">SMART FOOD REDISTRIBUTION</p>
        <p className="section-label">MAIN MENU</p>

        {navItems.map(([id, label, Icon]) => (
          <button
            key={id}
            className={tab === id ? "nav selected" : "nav"}
            onClick={() => setTab(id)}
          >
            <Icon size={19} />
            {label}
          </button>
        ))}

        <div className="sidebar-note">
          💚
          <p>Reduce waste.<br /><b>Feed people.</b></p>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <small>FOOD REDISTRIBUTION PLATFORM</small>
            <h1>Good food. Better future.</h1>
          </div>
          <span className="connected">● API Dashboard</span>
        </header>

        <section className="hero">
          <div>
            <small>TOGETHER, WE MAKE A DIFFERENCE</small>
            <h2>Rescue surplus food.<br />Share hope.</h2>
            <p>
              Connect food donors with NGOs and help good food
              reach people who need it.
            </p>
            <button className="primary" onClick={() => setTab("donate")}>
              <Plus size={18} /> Donate Food
            </button>
          </div>
          <div className="hero-emoji">🥗💚</div>
        </section>

        <section className="stats">
          <article>
            <Utensils />
            <p>Total food listings</p>
            <h2>{stats.total_food_listings}</h2>
          </article>
          <article>
            <PackageCheck />
            <p>Available food</p>
            <h2>{stats.available_food}</h2>
          </article>
          <article>
            <Users />
            <p>Registered NGOs</p>
            <h2>{stats.total_ngos}</h2>
          </article>
          <article>
            <Clock />
            <p>Claimed food</p>
            <h2>{stats.claimed_food}</h2>
          </article>
          <article>
            <CheckCircle />
            <p>Collected food</p>
            <h2>{stats.collected_food}</h2>
          </article>
          <article>
            <Heart />
            <p>Expired food</p>
            <h2>{stats.expired_food}</h2>
          </article>
        </section>

        <div className={`notice ${error ? "notice-error" : ""}`} hidden={!message}>
          <span>{message}</span>
          <button onClick={() => setMessage("")}>×</button>
        </div>

        {tab === "food" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Available Food</h2>
                <p>Track donations and update collection status.</p>
              </div>
              <button
                className="secondary"
                onClick={refreshDashboard}
                disabled={loading}
              >
                <RefreshCw size={16} />
                {loading ? "Loading..." : "Refresh"}
              </button>
            </div>

            {loading && foods.length === 0 ? (
              <p>Loading food listings...</p>
            ) : foods.length === 0 ? (
              <div className="empty">
                <div>🍱</div>
                <h3>No food listings yet</h3>
                <p>Be the first to donate surplus food.</p>
                <button className="primary" onClick={() => setTab("donate")}>
                  Add donation
                </button>
              </div>
            ) : (
              <div className="cards">
                {foods.map(item => (
                  <article className="food-card" key={item._id}>
                    <div className="dish">🥘</div>
                    <h3>{item.food_name}</h3>
                    <b>{item.quantity} {item.unit}</b>
                    <p><MapPin size={15} /> {item.location}</p>
                    <p>Donor: {item.donor_name}</p>

                    <span className={
                      item.priority === "urgent" ? "urgent tag" : "tag"
                    }>
                      {item.priority || item.status || "available"}
                    </span>

                    <p className="muted">
                      Expires: {new Date(item.expires_at).toLocaleString()}
                    </p>

                    <p className="status-line">
                      Status: <b>{item.status || "available"}</b>
                    </p>

                    {item.status === "available" && (
                      <button
                        className="primary action-button"
                        disabled={busyId === item._id}
                        onClick={() => updateFoodStatus(item, "claimed")}
                      >
                        {busyId === item._id ? "Updating..." : "Claim Food"}
                      </button>
                    )}

                    {item.status === "claimed" && (
                      <button
                        className="primary action-button"
                        disabled={busyId === item._id}
                        onClick={() => updateFoodStatus(item, "collected")}
                      >
                        {busyId === item._id ? "Updating..." : "Mark Collected"}
                      </button>
                    )}

                    {item.status === "collected" && (
                      <span className="tag">Successfully collected</span>
                    )}

                    {item.status === "expired" && (
                      <span className="urgent tag">Expired</span>
                    )}
                  </article>
                ))}
              </div>
            )}

            <div className="workflow-note">
              <h3><BarChart3 size={18} /> Donation workflow</h3>
              <p>Available → Claimed → Collected</p>
              <small>
                Claim Food and Mark Collected update the saved database record.
              </small>
            </div>
          </section>
        )}

        {tab === "donate" && (
          <section className="panel">
            <h2>Donate Surplus Food</h2>
            <p className="muted">Share your food donation details.</p>

            <form className="form-grid" onSubmit={addFood}>
              {field("Food name", food.food_name,
                v => setFood({ ...food, food_name: v }))}

              {field("Quantity", food.quantity,
                v => setFood({ ...food, quantity: v }),
                "number", { min: 0.1, step: "any" })}

              <label>
                Unit
                <select
                  value={food.unit}
                  onChange={e => setFood({ ...food, unit: e.target.value })}
                >
                  <option>kg</option>
                  <option>plates</option>
                  <option>packets</option>
                  <option>litres</option>
                </select>
              </label>

              {field("Donor name", food.donor_name,
                v => setFood({ ...food, donor_name: v }))}

              {field("Pickup location", food.location,
                v => setFood({ ...food, location: v }))}

              {field("Expiry date and time", food.expires_at,
                v => setFood({ ...food, expires_at: v }),
                "datetime-local")}

              <button className="primary full" disabled={loading}>
                Submit Donation
              </button>
            </form>
          </section>
        )}

        {tab === "register" && (
          <section className="panel">
            <h2>Register Your NGO</h2>
            <p className="muted">Join our food redistribution network.</p>

            <form className="form-grid" onSubmit={addNgo}>
              {field("NGO name", ngo.name,
                v => setNgo({ ...ngo, name: v }))}

              {field("Contact person", ngo.contact_person,
                v => setNgo({ ...ngo, contact_person: v }))}

              {field("Phone number", ngo.phone,
                v => setNgo({ ...ngo, phone: v }),
                "tel", { min: 1000000000 })}

              {field("Required quantity (kg)", ngo.required_quantity,
                v => setNgo({ ...ngo, required_quantity: v }),
                "number", { min: 0.1, step: "any" })}

              {field("Address", ngo.address,
                v => setNgo({ ...ngo, address: v }))}

              {field("Latitude", ngo.latitude,
                v => setNgo({ ...ngo, latitude: v }),
                "number", { min: -90, max: 90, step: "any" })}

              {field("Longitude", ngo.longitude,
                v => setNgo({ ...ngo, longitude: v }),
                "number", { min: -180, max: 180, step: "any" })}

              <button className="primary full">Register NGO</button>
            </form>

            <p className="muted">New registrations require verification.</p>
          </section>
        )}

        {tab === "nearby" && (
          <section className="panel">
            <h2>Find Nearby NGOs</h2>
            <p className="muted">Search by location and quantity.</p>

            <form className="form-grid" onSubmit={findNgos}>
              {field("Latitude", search.latitude,
                v => setSearch({ ...search, latitude: v }),
                "number", { min: -90, max: 90, step: "any" })}

              {field("Longitude", search.longitude,
                v => setSearch({ ...search, longitude: v }),
                "number", { min: -180, max: 180, step: "any" })}

              {field("Radius (km)", search.max_distance_km,
                v => setSearch({ ...search, max_distance_km: v }),
                "number", { min: 0.1, max: 100, step: "any" })}

              {field("Available quantity (kg)", search.quantity,
                v => setSearch({ ...search, quantity: v }),
                "number", { min: 0.1, step: "any" })}

              <button className="primary full">
                <Search size={18} /> Search Nearby NGOs
              </button>
            </form>

            <h3>Results: {ngos.length}</h3>
            {ngos.map(n => (
              <article className="ngo-card" key={n.id}>
                <Users />
                <div>
                  <h3>{n.name}</h3>
                  <p>{n.address}</p>
                  <p>{n.contact_person} · {n.phone}</p>
                  <small>
                    Needs {n.required_quantity} kg ·{" "}
                    {n.verified ? "Verified" : "Pending verification"}
                  </small>
                </div>
              </article>
            ))}

            {ngos.length === 0 && (
              <p className="muted">
                Search for NGOs to see matching organisations here.
              </p>
            )}
          </section>
        )}

        {tab === "ml" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2><BrainCircuit size={22} /> ML Delivery-Time Prediction</h2>
                <p>Estimate general food delivery duration using the trained Random Forest model.</p>
              </div>
            </div>

            <form className="form-grid" onSubmit={predictDelivery}>
              {field("Distance (km)", delivery.distance_km,
                v => setDelivery({ ...delivery, distance_km: v }),
                "number", { min: 0.1, step: "any" })}

              <label>
                Weather
                <select value={delivery.weather}
                  onChange={e => setDelivery({ ...delivery, weather: e.target.value })}>
                  <option>Clear</option><option>Rainy</option><option>Foggy</option><option>Windy</option><option>Stormy</option>
                </select>
              </label>

              <label>
                Traffic level
                <select value={delivery.traffic_level}
                  onChange={e => setDelivery({ ...delivery, traffic_level: e.target.value })}>
                  <option>Low</option><option>Medium</option><option>High</option>
                </select>
              </label>

              <label>
                Time of day
                <select value={delivery.time_of_day}
                  onChange={e => setDelivery({ ...delivery, time_of_day: e.target.value })}>
                  <option>Morning</option><option>Afternoon</option><option>Evening</option><option>Night</option>
                </select>
              </label>

              <label>
                Vehicle type
                <select value={delivery.vehicle_type}
                  onChange={e => setDelivery({ ...delivery, vehicle_type: e.target.value })}>
                  <option>Bike</option><option>Scooter</option><option>Car</option><option>Van</option><option>Bicycle</option>
                </select>
              </label>

              {field("Preparation time (minutes)", delivery.preparation_time_min,
                v => setDelivery({ ...delivery, preparation_time_min: v }),
                "number", { min: 0, step: "any" })}

              {field("Courier experience (years)", delivery.courier_experience_yrs,
                v => setDelivery({ ...delivery, courier_experience_yrs: v }),
                "number", { min: 0, step: "any" })}

              <button className="primary full" disabled={predicting}>
                <Truck size={18} /> {predicting ? "Predicting..." : "Predict Delivery Time"}
              </button>
            </form>

            {prediction && (
              <div className="workflow-note" role="status">
                <h3><Clock size={19} /> Estimated delivery time</h3>
                <h2>{Number(typeof prediction.prediction === "object" ? prediction.prediction?.predicted_delivery_time_minutes : prediction.prediction).toFixed(2)} minutes</h2>
                <p>Model: {prediction.prediction?.model || "Random Forest Regressor"}</p>
                <small>{prediction.notice}</small>
              </div>
            )}

            {modelMetrics && (
              <div className="workflow-note">
                <h3><BarChart3 size={19} /> Model evaluation</h3>
                <p>Dataset: <b>{modelMetrics.dataset}</b> · Rows: <b>{modelMetrics.total_rows}</b> (training {modelMetrics.training_rows}, testing {modelMetrics.testing_rows})</p>
                <p>R² score: <b>{Number(modelMetrics.r2_score).toFixed(4)}</b> · MAE: <b>{Number(modelMetrics.mae_minutes).toFixed(2)} minutes</b></p>
                <small>Metrics are from the dataset's held-out test split. This estimates general food delivery time and is not a validated food-rescue pickup-time guarantee.</small>
              </div>
            )}
          </section>
        )}

        <footer>
          FoodRescue360 © 2026 · Every meal matters.
        </footer>
      </main>
    </div>
  );
}
