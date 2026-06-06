import type { NextConfig } from "next";

import { loadFrontendConfig } from "./src/lib/projectConfig";

const frontendConfig = loadFrontendConfig();

const nextConfig: NextConfig = {
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_PREFIX: frontendConfig.api_prefix,
    NEXT_PUBLIC_API_URL: frontendConfig.api_url,
  },
  async rewrites() {
    return [
      {
        source: `${frontendConfig.api_prefix}/:path*`,
        destination: `${frontendConfig.api_url}${frontendConfig.api_prefix}/:path*`,
      },
    ];
  },
};

export default nextConfig;
