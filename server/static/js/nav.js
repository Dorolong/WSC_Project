import { initAuth, onAuthenticated } from "./auth.js";
import { initAuxiliary } from "./auxiliary.js";
import { initOptuna } from "./optuna.js";
import { initSimulator, setVehicleConfigProvider } from "./simulator.js";
import { getVehicleConfig, initVehicleConfig } from "./vehicle-config.js";

const views = {
  simulator: {
    tab: document.getElementById("tabSimulator"),
    panel: document.getElementById("simulatorView"),
  },
  optuna: {
    tab: document.getElementById("tabOptuna"),
    panel: document.getElementById("optunaView"),
  },
};

function activateView(name) {
  Object.entries(views).forEach(([key, view]) => {
    const isActive = key === name;
    view.tab.classList.toggle("is-active", isActive);
    view.panel.hidden = !isActive;
  });
}

function initNav() {
  views.simulator.tab.addEventListener("click", () => activateView("simulator"));
  views.optuna.tab.addEventListener("click", () => activateView("optuna"));
  activateView("simulator");
}

initNav();
initOptuna();
initAuxiliary();

let workspaceInitialized = false;
onAuthenticated(() => {
  if (workspaceInitialized) return;
  workspaceInitialized = true;
  initVehicleConfig()
    .then(() => {
      setVehicleConfigProvider(getVehicleConfig);
      initSimulator();
    })
    .catch((e) => {
      document.getElementById("simErr").textContent = e.message;
    });
});
initAuth();
