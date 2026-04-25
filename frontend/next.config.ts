import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export so the FastAPI backend can serve the built site from
  // backend/static/. Generates one HTML file per route under out/.
  output: "export",
};

export default nextConfig;
