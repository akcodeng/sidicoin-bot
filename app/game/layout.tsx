import type { Metadata, Viewport } from "next"

export const metadata: Metadata = {
  title: "Sidicoin Games",
  description: "Play games and win SIDI - Coin Flip, Dice Roll, Lucky Number",
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0a0a0a",
}

export default function GameLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
