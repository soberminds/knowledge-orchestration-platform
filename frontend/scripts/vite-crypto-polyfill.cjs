const crypto = require("node:crypto");

if (typeof crypto.getRandomValues !== "function") {
  if (crypto.webcrypto && typeof crypto.webcrypto.getRandomValues === "function") {
    crypto.getRandomValues = crypto.webcrypto.getRandomValues.bind(crypto.webcrypto);
  } else {
    crypto.getRandomValues = function getRandomValues(array) {
      return crypto.randomFillSync(array);
    };
  }
}
