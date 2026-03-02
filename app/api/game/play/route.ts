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

async function redisSet(key: string, value: unknown) {
  await fetch(`${REDIS_URL}/set/${key}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${REDIS_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(JSON.stringify(value)),
  })
}

// ─── Game Logic ──────────────────────────────────────────────────

function playCoinFlip(choice: string): { won: boolean; result: string } {
  const outcome = Math.random() < 0.5 ? "heads" : "tails"
  return {
    won: choice === outcome,
    result: `Coin landed on ${outcome.toUpperCase()}`,
  }
}

function playDiceRoll(choice: string): { won: boolean; result: string } {
  const roll = Math.floor(Math.random() * 6) + 1
  const isOver = roll > 3
  const won = (choice === "over" && isOver) || (choice === "under" && !isOver)
  return {
    won,
    result: `Dice rolled ${roll} (${isOver ? "Over" : "Under"} 3.5)`,
  }
}

function playLuckyNumber(choice: string): { won: boolean; result: string } {
  const drawn = Math.floor(Math.random() * 5) + 1
  return {
    won: String(drawn) === choice,
    result: `Lucky number was ${drawn}`,
  }
}

// ─── API Handler ─────────────────────────────────────────────────

const MAX_BET = 500
const MIN_BET = 1
const MULTIPLIERS: Record<string, number> = { coin: 2, dice: 2, lucky: 4.5 }

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { user_id, game, bet, choice } = body

    if (!user_id || !game || !bet || !choice) {
      return NextResponse.json({ error: "Missing fields" }, { status: 400 })
    }

    // Validate game type
    if (!["coin", "dice", "lucky"].includes(game)) {
      return NextResponse.json({ error: "Invalid game" }, { status: 400 })
    }

    // Validate bet
    const betAmount = parseFloat(bet)
    if (isNaN(betAmount) || betAmount < MIN_BET || betAmount > MAX_BET) {
      return NextResponse.json({ error: `Bet must be ${MIN_BET}-${MAX_BET} SIDI` }, { status: 400 })
    }

    // Get user
    const user = await redisGet(`user:${user_id}`)
    if (!user) {
      return NextResponse.json({ error: "User not found" }, { status: 404 })
    }

    const balance = parseFloat(user.sidi_balance || "0")
    if (balance < betAmount) {
      return NextResponse.json({ error: "Insufficient balance" }, { status: 400 })
    }

    // Check if banned
    if (user.is_banned) {
      return NextResponse.json({ error: "Account suspended" }, { status: 403 })
    }

    // Play the game
    let gameResult: { won: boolean; result: string }
    if (game === "coin") gameResult = playCoinFlip(choice)
    else if (game === "dice") gameResult = playDiceRoll(choice)
    else gameResult = playLuckyNumber(choice)

    // Calculate payout
    const multiplier = MULTIPLIERS[game] || 2
    const payout = gameResult.won ? betAmount * multiplier : 0
    const balanceChange = gameResult.won ? payout - betAmount : -betAmount
    const newBalance = Math.round((balance + balanceChange) * 100) / 100

    // Update user balance
    user.sidi_balance = newBalance

    // Track game stats
    user.games_played = (parseInt(user.games_played || "0") + 1)
    if (gameResult.won) {
      user.games_won = (parseInt(user.games_won || "0") + 1)
      user.total_game_winnings = parseFloat(user.total_game_winnings || "0") + payout
    }

    // Add to transaction history
    const txns = Array.isArray(user.transactions) ? user.transactions : []
    txns.unshift({
      type: gameResult.won ? "game_win" : "game_loss",
      amount: gameResult.won ? payout : betAmount,
      description: `${game === "coin" ? "Coin Flip" : game === "dice" ? "Dice Roll" : "Lucky Number"} - ${gameResult.result}`,
      timestamp: Math.floor(Date.now() / 1000),
      reference: `GAME-${Date.now()}`,
    })
    // Keep last 100 transactions
    user.transactions = txns.slice(0, 100)

    await redisSet(`user:${user_id}`, user)

    return NextResponse.json({
      won: gameResult.won,
      payout,
      result: gameResult.result,
      newBalance,
    })
  } catch (err) {
    console.error("Game play error:", err)
    return NextResponse.json({ error: "Server error" }, { status: 500 })
  }
}
