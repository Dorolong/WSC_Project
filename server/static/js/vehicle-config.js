import { getSupabaseClient } from "./auth.js";

let currentCfg = {};
let activeSection = "physics";

const sectionLabels = {
  physics: "Physics",
  solar: "Solar",
  cell: "Cell",
  pack: "Pack",
  power: "Power",
  drive: "Drive",
  race: "Race",
  simpara: "Simulation",
  ocv: "OCV",
};

const fields = {
  physics: [
    ["mass", "Total mass [kg]"],
    ["Cd", "Cd"],
    ["A_f", "Af [m^2]"],
    ["Crr", "Crr"],
    ["Drive_eff", "Drivetrain efficiency"],
    ["Air_Density", "Air density [kg/m^3]"],
    ["a_g", "Gravity [m/s^2]"],
  ],
  solar: [
    ["A_Solar", "Panel area [m^2]"],
    ["Solar_eff", "Panel efficiency"],
  ],
  cell: [
    ["V_batt_max", "Max voltage [V]"],
    ["V_batt_nom", "Nominal voltage [V]"],
    ["V_batt_min", "Cut-off voltage [V]"],
    ["Capa_batt", "Capacity [mAh]"],
    ["R_cell", "Internal resistance"],
  ],
  pack: [
    ["HV_S", "HV series"],
    ["HV_P", "HV parallel"],
    ["LV_S", "LV series"],
    ["LV_P", "LV parallel"],
  ],
  power: [
    ["P_LV_race", "Race LV consumption [W]"],
    ["P_LV_chg", "Stop LV consumption [W]"],
    ["Regen_eff", "Regen efficiency"],
    ["cs_chg_eff", "CS charge efficiency"],
  ],
  drive: [
    ["speed_constant", "Speed constant Kv [Vs/rad]"],
    ["torque_constant", "Torque constant Kt"],
    ["motor_nom_dcV", "Nominal DC voltage [V]"],
    ["motor_nom_speed", "Nominal speed [rad/s]"],
    ["motor_max_speed", "Max speed [rad/s]"],
    ["motor_nom_power", "Nominal power [W]"],
    ["nom_torque", "Nominal torque [Nm]"],
    ["max_torque", "Max torque [Nm]"],
    ["phase_res", "Phase resistance"],
    ["motor_eff", "Motor efficiency"],
    ["inverter_eff", "Inverter efficiency"],
    ["wheel_radius", "Wheel radius [m]"],
  ],
  race: [
    ["soc_start_min", "Minimum start SOC"],
    ["cs_stop_max", "CS max stop [s]"],
    ["cs_stop_min", "CS min stop [s]"],
    ["min_leg_avg_speed", "Min leg average speed [km/h]"],
    ["total_distance", "Total distance [m]"],
  ],
  simpara: [
    ["soc", "Initial SOC"],
    ["Accum_s", "Start seconds"],
    ["DY", "Start day"],
    ["HR", "Start hour"],
    ["prev_radiation", "Initial radiation"],
    ["prev_a", "Initial acceleration"],
    ["prev_v", "Initial speed"],
    ["prev_wind_speed", "Initial wind speed"],
    ["prev_wind_dir", "Initial wind direction"],
    ["prev_heading", "Initial heading"],
    ["soc_hard_stop", "SOC hard stop"],
    ["max_v_delta", "Max speed delta [m/s]"],
    ["avg_traffic_light_delay", "Traffic delay [s]"],
    ["avg_pedestrian_light_delay", "Pedestrian delay [s]"],
    ["decel_brake", "CS braking [g]"],
  ],
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function setError(message) {
  document.getElementById("vehicleConfigErr").textContent = message || "";
}

function renderTabs() {
  const tabs = document.getElementById("vehicleConfigTabs");
  tabs.innerHTML = Object.keys(sectionLabels)
    .map((key) => `<button class="tab ${key === activeSection ? "is-active" : ""}" type="button" data-section="${key}">${sectionLabels[key]}</button>`)
    .join("");
  tabs.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      readVisibleFields();
      activeSection = btn.dataset.section;
      renderConfig();
    });
  });
}

function renderFields() {
  const grid = document.getElementById("vehicleConfigFields");
  const ocv = document.getElementById("ocvEditor");
  if (activeSection === "ocv") {
    grid.hidden = true;
    ocv.hidden = false;
    renderOcvRows();
    return;
  }

  grid.hidden = false;
  ocv.hidden = true;
  grid.innerHTML = (fields[activeSection] || [])
    .map(([key, label]) => {
      const value = currentCfg[activeSection]?.[key] ?? 0;
      return `<label class="field-row">${label}<input type="number" step="any" data-key="${key}" value="${value}" /></label>`;
    })
    .join("");
}

function renderOcvRows() {
  const soc = currentCfg.cell?.ocv_soc || [];
  const volts = currentCfg.cell?.ocv_V || [];
  document.getElementById("ocvRows").innerHTML = soc
    .map((value, i) => `
      <tr>
        <td><input type="number" step="any" data-ocv="soc" data-index="${i}" value="${value}" /></td>
        <td><input type="number" step="any" data-ocv="volts" data-index="${i}" value="${volts[i]}" /></td>
      </tr>
    `)
    .join("");
}

function readVisibleFields() {
  if (!currentCfg.cell) return;
  if (activeSection === "ocv") {
    document.querySelectorAll("[data-ocv='soc']").forEach((input) => {
      currentCfg.cell.ocv_soc[parseInt(input.dataset.index, 10)] = Number(input.value);
    });
    document.querySelectorAll("[data-ocv='volts']").forEach((input) => {
      currentCfg.cell.ocv_V[parseInt(input.dataset.index, 10)] = Number(input.value);
    });
    return;
  }

  document.querySelectorAll("#vehicleConfigFields [data-key]").forEach((input) => {
    currentCfg[activeSection][input.dataset.key] = Number(input.value);
  });
}

function renderConfig() {
  renderTabs();
  renderFields();
}

async function loadDefaultConfig() {
  const res = await fetch("/api/sim/default-config");
  if (!res.ok) throw new Error("Default vehicle settings failed to load.");
  const data = await res.json();
  currentCfg = clone(data.cfg);
  renderConfig();
}

async function loadSavedConfig() {
  setError("");
  try {
    const client = await getSupabaseClient();
    const { data: userData, error: userError } = await client.auth.getUser();
    if (userError) throw userError;
    const { data, error } = await client
      .from("user_settings")
      .select("vehicle_cfg")
      .eq("user_id", userData.user.id)
      .maybeSingle();
    if (error) throw error;
    if (!data?.vehicle_cfg) {
      setError("No saved settings found.");
      return;
    }
    currentCfg = clone(data.vehicle_cfg);
    renderConfig();
  } catch (e) {
    setError(e.message || "Saved settings failed to load.");
  }
}

async function saveConfig() {
  readVisibleFields();
  setError("");
  try {
    const client = await getSupabaseClient();
    const { data: userData, error: userError } = await client.auth.getUser();
    if (userError) throw userError;
    const { error } = await client
      .from("user_settings")
      .upsert({ user_id: userData.user.id, vehicle_cfg: currentCfg });
    if (error) throw error;
    setError("Saved.");
  } catch (e) {
    setError(e.message || "Save failed.");
  }
}

function openDialog() {
  renderConfig();
  document.getElementById("vehicleConfigDialog").showModal();
}

export function getVehicleConfig() {
  readVisibleFields();
  return clone(currentCfg);
}

export async function initVehicleConfig() {
  await loadDefaultConfig();
  document.getElementById("vehicleConfigBtn").addEventListener("click", openDialog);
  document.getElementById("vehicleConfigClose").addEventListener("click", () => {
    document.getElementById("vehicleConfigDialog").close();
  });
  document.getElementById("vehicleConfigLoad").addEventListener("click", loadSavedConfig);
  document.getElementById("vehicleConfigSave").addEventListener("click", saveConfig);
  document.getElementById("vehicleConfigApply").addEventListener("click", () => {
    readVisibleFields();
    document.getElementById("vehicleConfigDialog").close();
  });
}
