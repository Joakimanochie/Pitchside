// Every page is built ahead of time. The pages under /app read the data files the daily pipeline writes (see scripts/export_app_data.py);
// the public pages (landing, about, terms, privacy, responsible gambling) read nothing, so no prediction ever appears in their HTML.
export const prerender = true;
