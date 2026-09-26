/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Dev only: proxy API/WS to the gateway so `npm run dev` works against the compose stack.
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [{ source: "/api/:path*", destination: "http://localhost:3000/api/:path*" }]
      : [];
  },
};
export default nextConfig;
