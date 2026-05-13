/** @type {import('next').NextConfig} */
const API_ORIGIN = process.env.FLUX_API_ORIGIN ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Same-origin proxy: cookies issued by the API live on localhost:3000
    // (no CORS hassle) and the GitHub OAuth callback can be registered at
    // http://localhost:3000/auth/github/callback.
    return [
      { source: "/auth/:path*", destination: `${API_ORIGIN}/auth/:path*` },
      { source: "/api/:path*", destination: `${API_ORIGIN}/:path*` },
    ];
  },
};

export default nextConfig;
