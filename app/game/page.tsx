"use client"

import { useState, useEffect, useCallback } from "react"

// ─── Types ───────────────────────────────────────────────────────
type GameType = "coin" | "dice" | "lucky"
type GameState = "idle" | "betting" | "playing" | "result"

interface GameResult {
  won: boolean
  payout: number
  result: string
  newBalance: number
}

// ─── Constants ───────────────────────────────────────────────────
const BET_OPTIONS = [5, 10, 25, 50, 100]

const GAMES: { id: GameType; name: string; icon: string; desc: string; odds: string }[] = [
  { id: "coin", name: "Coin Flip", icon: "\u{1FA99}", desc: "Heads or Tails", odds: "2x" },
  { id: "dice", name: "Dice Roll", icon: "\u{1F3B2}", desc: "Over or Under", odds: "2x" },
  { id: "lucky", name: "Lucky Number", icon: "\u2B50", desc: "Pick 1-5", odds: "4.5x" },
]

// ─── Helpers ─────────────────────────────────────────────────────
function fmt(n: number) {
  return n.toLocaleString("en-US", { maximumFractionDigits: 1 })
}

// ─── Main Component ──────────────────────────────────────────────
export default function GamePage() {
  const [tg, setTg] = useState<any>(null)
  const [userId, setUserId] = useState<string>("")
  const [balance, setBalance] = useState<number>(0)
  const [loading, setLoading] = useState(true)

  const [activeGame, setActiveGame] = useState<GameType | null>(null)
  const [gameState, setGameState] = useState<GameState>("idle")
  const [betAmount, setBetAmount] = useState<number>(10)
  const [choice, setChoice] = useState<string>("")
  const [result, setResult] = useState<GameResult | null>(null)
  const [animating, setAnimating] = useState(false)

  // Init Telegram WebApp
  useEffect(() => {
    const script = document.createElement("script")
    script.src = "https://telegram.org/js/telegram-web-app.js"
    script.onload = () => {
      const webapp = (window as any).Telegram?.WebApp
      if (webapp) {
        webapp.ready()
        webapp.expand()
        webapp.setHeaderColor("#0a0a0a")
        webapp.setBackgroundColor("#0a0a0a")
        setTg(webapp)
        const user = webapp.initDataUnsafe?.user
        if (user?.id) {
          setUserId(String(user.id))
          fetchBalance(String(user.id))
        } else {
          setLoading(false)
        }
      } else {
        setLoading(false)
      }
    }
    document.head.appendChild(script)
    return () => { script.remove() }
  }, [])

  const fetchBalance = async (uid: string) => {
    try {
      const res = await fetch(`/api/game/balance?user_id=${uid}`)
      const data = await res.json()
      if (data.balance !== undefined) setBalance(data.balance)
    } catch { /* ignore */ }
    setLoading(false)
  }

  const playGame = useCallback(async () => {
    if (!activeGame || !choice || !userId) return
    setGameState("playing")
    setAnimating(true)

    // Animation delay
    await new Promise((r) => setTimeout(r, 1500))

    try {
      const res = await fetch("/api/game/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          game: activeGame,
          bet: betAmount,
          choice,
          init_data: tg?.initData || "",
        }),
      })
      const data = await res.json()
      if (data.error) {
        setAnimating(false)
        setGameState("betting")
        return
      }
      setResult(data)
      setBalance(data.newBalance)
      setAnimating(false)
      setGameState("result")

      // Haptic feedback
      if (tg?.HapticFeedback) {
        data.won
          ? tg.HapticFeedback.notificationOccurred("success")
          : tg.HapticFeedback.notificationOccurred("error")
      }
    } catch {
      setAnimating(false)
      setGameState("betting")
    }
  }, [activeGame, choice, betAmount, userId, tg])

  const resetGame = () => {
    setGameState("idle")
    setActiveGame(null)
    setChoice("")
    setResult(null)
  }

  const selectGame = (g: GameType) => {
    setActiveGame(g)
    setGameState("betting")
    setChoice("")
    setResult(null)
  }

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a0a0a]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-neutral-400 text-sm font-mono">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white flex flex-col select-none">
      {/* Header */}
      <header className="flex items-center justify-between px-5 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center text-xs font-bold text-black">
            S
          </div>
          <span className="text-sm font-semibold text-neutral-300">SidiApp Games</span>
        </div>
        {activeGame && gameState !== "idle" && (
          <button
            onClick={resetGame}
            className="text-xs text-neutral-500 hover:text-white transition-colors px-3 py-1.5 rounded-full border border-neutral-800"
          >
            Back
          </button>
        )}
      </header>

      {/* Balance Bar */}
      <div className="mx-5 mb-4 px-4 py-3 rounded-2xl bg-gradient-to-r from-neutral-900 to-neutral-800 border border-neutral-800">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-neutral-500 font-mono">Balance</p>
            <p className="text-2xl font-bold text-white mt-0.5">
              {fmt(balance)} <span className="text-amber-500 text-sm font-medium">SIDI</span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-widest text-neutral-500 font-mono">Value</p>
            <p className="text-sm text-neutral-300 mt-0.5 font-mono">
              {'\u20A6'}{fmt(balance * 25)}
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 px-5 pb-8">
        {gameState === "idle" && <GameSelector onSelect={selectGame} />}
        {gameState === "betting" && activeGame && (
          <BettingScreen
            game={activeGame}
            bet={betAmount}
            setBet={setBetAmount}
            choice={choice}
            setChoice={setChoice}
            balance={balance}
            onPlay={playGame}
          />
        )}
        {gameState === "playing" && activeGame && (
          <PlayingScreen game={activeGame} animating={animating} />
        )}
        {gameState === "result" && result && activeGame && (
          <ResultScreen result={result} game={activeGame} bet={betAmount} onPlayAgain={() => { setGameState("betting"); setChoice(""); setResult(null) }} onBack={resetGame} />
        )}
      </div>
    </div>
  )
}

// ─── Sub Components ──────────────────────────────────────────────

function GameSelector({ onSelect }: { onSelect: (g: GameType) => void }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-bold text-white mb-1">Choose a Game</h2>
      {GAMES.map((g) => (
        <button
          key={g.id}
          onClick={() => onSelect(g.id)}
          className="w-full p-4 rounded-2xl bg-neutral-900 border border-neutral-800 hover:border-amber-500/50 transition-all active:scale-[0.98] flex items-center gap-4"
        >
          <div className="w-14 h-14 rounded-xl bg-neutral-800 flex items-center justify-center text-2xl flex-shrink-0">
            {g.icon}
          </div>
          <div className="flex-1 text-left">
            <p className="font-semibold text-white">{g.name}</p>
            <p className="text-xs text-neutral-500 mt-0.5">{g.desc}</p>
          </div>
          <div className="px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20">
            <span className="text-xs font-bold text-amber-400">{g.odds}</span>
          </div>
        </button>
      ))}

      <div className="mt-4 p-4 rounded-2xl bg-neutral-900/50 border border-neutral-800/50">
        <p className="text-[10px] uppercase tracking-widest text-neutral-600 font-mono mb-2">How it works</p>
        <div className="space-y-1.5 text-xs text-neutral-400 leading-relaxed">
          <p>{'1.'} Pick a game and place your bet in SIDI</p>
          <p>{'2.'} Make your choice and hit Play</p>
          <p>{'3.'} Win and your payout is added instantly</p>
        </div>
      </div>
    </div>
  )
}

function BettingScreen({
  game, bet, setBet, choice, setChoice, balance, onPlay,
}: {
  game: GameType; bet: number; setBet: (n: number) => void
  choice: string; setChoice: (s: string) => void; balance: number
  onPlay: () => void
}) {
  const gameInfo = GAMES.find((g) => g.id === game)!
  const canPlay = choice && bet <= balance && bet > 0

  return (
    <div className="flex flex-col gap-5">
      {/* Game Header */}
      <div className="text-center">
        <div className="text-4xl mb-2">{gameInfo.icon}</div>
        <h2 className="text-xl font-bold">{gameInfo.name}</h2>
        <p className="text-xs text-neutral-500 mt-1">Win up to {gameInfo.odds} your bet</p>
      </div>

      {/* Bet Amount */}
      <div>
        <p className="text-[10px] uppercase tracking-widest text-neutral-500 font-mono mb-2">Bet Amount</p>
        <div className="flex gap-2 flex-wrap">
          {BET_OPTIONS.map((opt) => (
            <button
              key={opt}
              onClick={() => setBet(opt)}
              disabled={opt > balance}
              className={`flex-1 min-w-[60px] py-2.5 rounded-xl text-sm font-semibold transition-all ${
                bet === opt
                  ? "bg-amber-500 text-black"
                  : opt > balance
                  ? "bg-neutral-900 text-neutral-700 border border-neutral-800"
                  : "bg-neutral-900 text-white border border-neutral-700 hover:border-amber-500/50"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>

      {/* Choice */}
      <div>
        <p className="text-[10px] uppercase tracking-widest text-neutral-500 font-mono mb-2">Your Pick</p>
        {game === "coin" && (
          <div className="grid grid-cols-2 gap-3">
            {["heads", "tails"].map((c) => (
              <button
                key={c}
                onClick={() => setChoice(c)}
                className={`py-4 rounded-xl text-sm font-semibold transition-all ${
                  choice === c
                    ? "bg-amber-500 text-black border-amber-500"
                    : "bg-neutral-900 text-white border border-neutral-700 hover:border-amber-500/50"
                } border`}
              >
                {c === "heads" ? "\u{1FA99} Heads" : "\u{1FA99} Tails"}
              </button>
            ))}
          </div>
        )}
        {game === "dice" && (
          <div className="grid grid-cols-2 gap-3">
            {["over", "under"].map((c) => (
              <button
                key={c}
                onClick={() => setChoice(c)}
                className={`py-4 rounded-xl text-sm font-semibold transition-all ${
                  choice === c
                    ? "bg-amber-500 text-black border-amber-500"
                    : "bg-neutral-900 text-white border border-neutral-700 hover:border-amber-500/50"
                } border`}
              >
                {c === "over" ? "\u2B06\uFE0F Over 3.5" : "\u2B07\uFE0F Under 3.5"}
              </button>
            ))}
          </div>
        )}
        {game === "lucky" && (
          <div className="grid grid-cols-5 gap-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => setChoice(String(n))}
                className={`py-4 rounded-xl text-lg font-bold transition-all ${
                  choice === String(n)
                    ? "bg-amber-500 text-black border-amber-500"
                    : "bg-neutral-900 text-white border border-neutral-700 hover:border-amber-500/50"
                } border`}
              >
                {n}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Potential Win */}
      {choice && (
        <div className="px-4 py-3 rounded-xl bg-amber-500/5 border border-amber-500/20 text-center">
          <p className="text-xs text-neutral-400">Potential win</p>
          <p className="text-xl font-bold text-amber-400 mt-0.5">
            {fmt(bet * (game === "lucky" ? 4.5 : 2))} SIDI
          </p>
        </div>
      )}

      {/* Play Button */}
      <button
        onClick={onPlay}
        disabled={!canPlay}
        className={`w-full py-4 rounded-2xl text-base font-bold transition-all active:scale-[0.97] ${
          canPlay
            ? "bg-gradient-to-r from-amber-500 to-amber-600 text-black shadow-lg shadow-amber-500/25"
            : "bg-neutral-800 text-neutral-600"
        }`}
      >
        {!choice ? "Make your pick" : bet > balance ? "Insufficient balance" : `Play for ${bet} SIDI`}
      </button>
    </div>
  )
}

function PlayingScreen({ game, animating }: { game: GameType; animating: boolean }) {
  const gameInfo = GAMES.find((g) => g.id === game)!

  return (
    <div className="flex-1 flex flex-col items-center justify-center min-h-[300px]">
      <div className={`text-7xl mb-6 ${animating ? "animate-bounce" : ""}`}>
        {gameInfo.icon}
      </div>
      <p className="text-lg font-semibold text-white animate-pulse">
        {game === "coin" ? "Flipping..." : game === "dice" ? "Rolling..." : "Drawing..."}
      </p>
      <div className="flex gap-1 mt-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"
            style={{ animationDelay: `${i * 200}ms` }}
          />
        ))}
      </div>
    </div>
  )
}

function ResultScreen({
  result, game, bet, onPlayAgain, onBack,
}: {
  result: GameResult; game: GameType; bet: number
  onPlayAgain: () => void; onBack: () => void
}) {
  return (
    <div className="flex flex-col items-center gap-5 pt-4">
      {/* Result Icon */}
      <div className={`w-24 h-24 rounded-full flex items-center justify-center text-5xl ${
        result.won
          ? "bg-green-500/10 border-2 border-green-500/30"
          : "bg-red-500/10 border-2 border-red-500/30"
      }`}>
        {result.won ? "\u{1F389}" : "\u{1F614}"}
      </div>

      {/* Title */}
      <div className="text-center">
        <h2 className={`text-2xl font-bold ${result.won ? "text-green-400" : "text-red-400"}`}>
          {result.won ? "You Won!" : "Not This Time"}
        </h2>
        <p className="text-sm text-neutral-400 mt-1">{result.result}</p>
      </div>

      {/* Payout Card */}
      <div className={`w-full p-5 rounded-2xl border ${
        result.won
          ? "bg-green-500/5 border-green-500/20"
          : "bg-neutral-900 border-neutral-800"
      }`}>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-neutral-500">Bet</span>
          <span className="text-sm font-mono text-white">{fmt(bet)} SIDI</span>
        </div>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-neutral-500">{result.won ? "Won" : "Lost"}</span>
          <span className={`text-sm font-mono font-bold ${result.won ? "text-green-400" : "text-red-400"}`}>
            {result.won ? "+" : "-"}{fmt(result.won ? result.payout : bet)} SIDI
          </span>
        </div>
        <div className="h-px bg-neutral-800 my-3" />
        <div className="flex items-center justify-between">
          <span className="text-xs text-neutral-500">Balance</span>
          <span className="text-base font-bold text-white font-mono">{fmt(result.newBalance)} SIDI</span>
        </div>
      </div>

      {/* Buttons */}
      <div className="flex gap-3 w-full">
        <button
          onClick={onBack}
          className="flex-1 py-3.5 rounded-xl text-sm font-semibold bg-neutral-900 text-white border border-neutral-700 hover:border-neutral-600 transition-all"
        >
          Games
        </button>
        <button
          onClick={onPlayAgain}
          className="flex-1 py-3.5 rounded-xl text-sm font-bold bg-gradient-to-r from-amber-500 to-amber-600 text-black transition-all active:scale-[0.97]"
        >
          Play Again
        </button>
      </div>
    </div>
  )
}
