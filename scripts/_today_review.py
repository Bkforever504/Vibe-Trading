#!/usr/bin/env python3
import yfinance as yf

spy = yf.download('SPY', period='1d', interval='1m', progress=False, auto_adjust=True)
spy.columns = spy.columns.get_level_values(0)

orb = spy.between_time('09:30', '09:35')
orb_high = orb['High'].max()
orb_low  = orb['Low'].min()

def price_at(t):
    s = spy[spy.index.strftime('%H:%M') <= t]
    return s['Close'].iloc[-1] if not s.empty else None

open_p  = price_at('09:31')
p1000   = price_at('10:00')
p1030   = price_at('10:30')
p1200   = price_at('12:00')
p1345   = price_at('13:45')
close_p = spy['Close'].iloc[-1]
day_high = spy['High'].max()
day_low  = spy['Low'].min()

print(f"SPY Aug 5 2026")
print(f"ORB:   high={orb_high:.2f}  low={orb_low:.2f}  range={((orb_high-orb_low)/orb_low*100):.2f}%")
print(f"Open:  {open_p:.2f}")
print(f"10:00: {p1000:.2f}  vs ORB_high: {((p1000-orb_high)/orb_high*100):+.2f}%")
print(f"10:30: {p1030:.2f}  vs ORB_high: {((p1030-orb_high)/orb_high*100):+.2f}%")
print(f"12:00: {p1200:.2f}")
print(f"13:45: {p1345:.2f}  (hard close time)")
print(f"Close: {close_p:.2f}")
print(f"Range: {day_high:.2f} - {day_low:.2f}  (total: {day_high-day_low:.2f} pts)")
direction = "BULL" if close_p > orb_high else "BEAR" if close_p < orb_low else "NEUTRAL"
print(f"ORB outcome: {direction}")

if open_p and orb_high:
    gap_from_orb = (close_p - orb_high) / orb_high * 100
    print(f"Close vs ORB high: {gap_from_orb:+.2f}%")

try:
    tick = yf.download('^TICK', period='1d', interval='1m', progress=False, auto_adjust=True)
    tick.columns = tick.columns.get_level_values(0) if hasattr(tick.columns, 'get_level_values') else tick.columns
    if not tick.empty:
        th = tick['High'].max()
        tl = tick['Low'].min()
        print(f"\nTICK extreme high: {th:.0f}  exhaustion_top (>=1000): {th >= 1000}")
        print(f"TICK extreme low:  {tl:.0f}  exhaustion_bottom (<=-1000): {tl <= -1000}")
except Exception as e:
    print(f"TICK unavailable: {e}")

# What a 762 CALL would have done (rough estimate based on move)
print(f"\n--- TRADE SIMULATION (if bot had fired at ORB breakout) ---")
entry_spot = orb_high
print(f"Entry at ORB breakout: SPY ~{entry_spot:.2f}")
print(f"ATM call strike: ~{round(entry_spot):d}")
move_by_1345 = p1345 - entry_spot if p1345 else 0
print(f"SPY move to 13:45: {move_by_1345:+.2f} pts")
