import { NextRequest, NextResponse } from "next/server"

const REDIS_URL = process.env.UPSTASH_REDIS_REST_URL || ""
const REDIS_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || ""

async function redisGet(key: string) {
  const res = await fetch(`${REDIS_URL}/get/${key}`, {
    headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
  })
  const data = await res.json()
  if (data.result) {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return null
}

export async function GET(req: NextRequest) {
  const userId = req.nextUrl.searchParams.get("user_id")
  if (!userId) return NextResponse.json({ error: "Missing user_id" }, { status: 400 })

  const user = await redisGet(`user:${userId}`)
  if (!user) return NextResponse.json({ error: "User not found" }, { status: 404 })

  return NextResponse.json({
    balance: parseFloat(user.sidi_balance || "0"),
    username: user.username || "",
  })
}
