/** @type {import('next').NextConfig} */
const nextConfig = {
  // Cloud Runでの実行を前提に standalone 出力にする(Dockerイメージを小さくできる)。
  output: "standalone",
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
