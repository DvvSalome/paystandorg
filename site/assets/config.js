/* Runtime settings. Nothing secret goes here: this file is public. */
window.GA27_CONFIG = {
  // Base URL of the submission API (Supabase Edge Function). Empty = preview build,
  // the form validates but nothing is sent. Contract: docs/submission-api.md
  endpoint: "https://gkaukpnmpfdpljofnlxy.supabase.co/functions/v1/intake",
  // Supabase publishable key (public by design). Sent as `apikey` on file uploads.
  supabaseKey: "sb_publishable_aqZUk3Y2j3aGq3_Eh2o9XQ_50QfQnGf",
  // Cloudflare Turnstile site key (public). Empty = no captcha widget.
  turnstileSiteKey: "",
  maxFileMB: 10,
  // true once the server emails the draft code (docs/email-the-code.md).
  // While false the form never claims it sent anything: it tells people to
  // write the code down, because a lost code cannot be recovered.
  emailCodes: false
};
