/* Runtime settings. Nothing secret goes here: this file is public. */
window.GA27_CONFIG = {
  // Base URL of the submission API (Supabase Edge Function). Empty = preview build,
  // the form validates but nothing is sent. Contract: docs/submission-api.md
  endpoint: "",
  // Cloudflare Turnstile site key (public). Empty = no captcha widget.
  turnstileSiteKey: "",
  maxFileMB: 10
};
