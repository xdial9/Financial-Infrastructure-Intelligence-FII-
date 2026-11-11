// Synthetic fixture; no live financial institution or provider is represented.
const accountRoute = "/api/v2/accounts";
fetch("/api/v2/accounts", { method: "POST" });
axios.get("https://api.example.invalid/v1/institutions");
const xhr = new XMLHttpRequest();
xhr.open("GET", "/oauth/authorize", true);

const identityMetadata = {
  issuer: "https://identity.example.invalid",
  authorization_endpoint: "https://identity.example.invalid/oauth/authorize",
  token_endpoint: "https://identity.example.invalid/oauth/token",
  client_id: "synthetic-public-client-id",
  code_challenge_method: "S256"
};

const bankLinkProvider = "Plaid Link";
const paymentProvider = "Stripe";
const localSecretPlaceholder = { client_secret: "synthetic-placeholder-not-a-secret" };
const headerPlaceholder = "Bearer synthetic-bearer-placeholder";
//# sourceMappingURL=app.js.map
