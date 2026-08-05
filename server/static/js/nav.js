import { initAuth } from "./auth.js";
import { initOptuna } from "./optuna.js";

function initNav() {
  document.getElementById("tabOptuna").classList.add("is-active");
}

initNav();
initOptuna();
initAuth();
