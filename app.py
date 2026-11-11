"""Kalshi BTC 15-minute late-entry PAPER trader. No orders or API keys."""
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

API = 'https://external-api.kalshi.com/trade-api/v2'
COINBASE = 'https://api.exchange.coinbase.com'
HEADERS = {'User-Agent': 'KalshiLatePaperBot/1.0', 'Accept': 'application/json'}


def get_json(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=9)
    r.raise_for_status()
    return r.json()


def cents(value, dollar=False):
    if value is None or value == '':
        return None
    try:
        n = float(value)
        return n * 100 if dollar else n
    except (ValueError, TypeError):
        return None


def market_price(m, prefix):
    for field, is_dollar in ((prefix + '_dollars', True), (prefix, False)):
        if m.get(field) is not None:
            return cents(m[field], is_dollar)
    return None


def orderbook(ticker):
    """Read Kalshi fixed-point orderbook (and legacy format) safely.

    Kalshi's current response uses top-level `orderbook_fp`, not `orderbook`.
    Missing/empty sides remain unavailable; never synthesize a fill price.
    """
    response = get_json(f'{API}/markets/{quote(ticker, safe="")}/orderbook')
    if not isinstance(response, dict):
        raise ValueError('Unexpected Kalshi orderbook response type')
    if isinstance(response.get('orderbook_fp'), dict):
        raw = response['orderbook_fp']
    elif isinstance(response.get('orderbook'), dict):
        raw = response['orderbook']
    else:
        raise ValueError('Kalshi response has no recognized orderbook_fp/orderbook object')

    def levels(side):
        if side + '_dollars' in raw:
            data, dollar = raw[side + '_dollars'], True
        elif side in raw:
            data, dollar = raw[side], False
        else:
            raise ValueError(f'Kalshi orderbook missing {side} levels')
        if isinstance(data, dict):
            data = data.get('bids', [])
        if not isinstance(data, list):
            raise ValueError(f'Unexpected {side} orderbook levels format')
        found = []
        for level in data:
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price_raw, size_raw = level[:2]
            elif isinstance(level, dict):
                price_raw = level.get('price_dollars') if dollar else level.get('price')
                size_raw = level.get('count_fp', level.get('quantity', level.get('count', 0)))
            else:
                continue
            try:
                price = round(cents(price_raw, dollar), 6)
                size = float(size_raw)
            except (ValueError, TypeError):
                continue
            if price is not None and math.isfinite(price) and math.isfinite(size) and 0 < price < 100 and size > 0:
                found.append((price, size))
        return sorted(found, key=lambda x: x[0], reverse=True)

    y, n = levels('yes'), levels('no')
    return {
        'YES': {'bid': y[0][0] if y else None, 'bid_size': y[0][1] if y else 0,
                'ask': round(100 - n[0][0], 4) if n else None, 'ask_size': n[0][1] if n else 0},
        'NO': {'bid': n[0][0] if n else None, 'bid_size': n[0][1] if n else 0,
               'ask': round(100 - y[0][0], 4) if y else None, 'ask_size': y[0][1] if y else 0},
    }


def utc_ts(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def find_market(now):
    data = get_json(f'{API}/markets', {'series_ticker': 'KXBTC15M', 'status': 'open', 'limit': 100})
    options = []
    for m in data.get('markets', []):
        end = utc_ts(m.get('close_time') or m.get('expiration_time'))
        start = utc_ts(m.get('open_time'))
        if end and start is None:
            start = end - 900  # rolling 15-minute market
        if end and start and start <= now < end and m.get('ticker', '').startswith('KXBTC15M-'):
            options.append((end, m, start))
    if not options:
        return None, None, None
    options.sort(key=lambda x: x[0])
    end, m, start = options[0]
    # Refresh exact market: market list may omit floor_strike.
    full = get_json(f'{API}/markets/{quote(m["ticker"], safe="")}').get('market', {})
    m.update(full)
    return m, start, end


def btc_spot_and_volatility():
    # Coinbase is a proxy, NOT necessarily Kalshi's official settlement index.
    ticker = get_json(f'{COINBASE}/products/BTC-USD/ticker')
    spot = float(ticker['price'])
    raw = get_json(f'{COINBASE}/products/BTC-USD/candles', {'granularity': 60})
    # Coinbase candles: [epoch, low, high, open, close, volume]
    bars = sorted((r for r in raw if len(r) >= 5), key=lambda r: r[0])[-61:]
    if len(bars) < 25:
        raise ValueError('Not enough recent 1-minute BTC candles for volatility estimate')
    closes = [float(r[4]) for r in bars]
    returns = [math.log(b/a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    sigma = float(pd.Series(returns).std())
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError('Volatility estimate unavailable')
    age = time.time() - float(bars[-1][0])
    if age > 240:
        raise ValueError('BTC candle data too stale')
    return spot, sigma


def db_connect():
    url = os.getenv('DATABASE_URL')
    try:
        url = st.secrets.get('DATABASE_URL', url)
    except (FileNotFoundError, KeyError):
        pass
    if url:
        import psycopg
        conn = psycopg.connect(url, connect_timeout=8)
        return conn, True
    return sqlite3.connect('late_paper_local.sqlite3', timeout=10), False


def db_execute(conn, pg, sql, params=(), fetch=False):
    if pg:
        sql = sql.replace('?', '%s')
    cur = conn.cursor()
    cur.execute(sql, params)
    result = cur.fetchall() if fetch else None
    conn.commit()
    cur.close()
    return result


def init_db(conn, pg):
    db_execute(conn, pg, 'CREATE TABLE IF NOT EXISTS late_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')


def load_state(conn, pg):
    rows = db_execute(conn, pg, 'SELECT value FROM late_state WHERE key=?', ('state',), True)
    if rows:
        try:
            return json.loads(rows[0][0])
        except (ValueError, TypeError):
            pass
    return {'balance': 1000.0, 'position': None, 'trades': [], 'used': [], 'event': 'Ready'}


def save_state(conn, pg, state):
    db_execute(conn, pg, 'INSERT INTO late_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               ('state', json.dumps(state)))


def fee_estimate(price_cents, qty):
    # Approximate Kalshi taker fee, rounded up to the nearest cent per order.
    p = max(0, min(1, price_cents/100))
    return math.ceil(100 * 0.07 * qty * p * (1-p) - 1e-9) / 100


def close_position(state, exit_cents, reason, now, fee=0.0):
    pos = state['position']
    if pos is None:
        return
    qty = pos['qty']
    pnl = round((exit_cents - pos['entry']) * qty / 100 - pos['entry_fee'] - fee, 4)
    state['balance'] = round(state['balance'] + exit_cents*qty/100 - fee, 4)
    state['trades'].append({**pos, 'exit': exit_cents, 'exit_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                            'exit_reason': reason, 'exit_fee': fee, 'net_pnl': pnl})
    state['position'] = None
    state['event'] = f'Closed {reason}: {pnl:+.2f} USD'


st.set_page_config(page_title='BTC Late Entry | Paper', page_icon='⏳', layout='wide')
st.title('⏳ Kalshi BTC 15m — Late Entry PAPER Bot')
st.caption('Separate strategy. Public market data only; NO REAL ORDERS. Monitors only while this Streamlit session is active.')

with st.sidebar:
    st.header('Late-entry rules')
    auto = st.checkbox('Automatically enter paper trades', value=False,
                       help='Enable only after checking market, quotes, and risk settings.')
    min_ask = st.slider('Minimum ask (¢)', 60, 95, 80)
    max_ask = st.slider('Maximum ask (¢)', min_ask, 99, 90)
    max_remaining = st.slider('Earliest entry (minutes remaining)', 2, 8, 5)
    min_remaining = st.slider('Latest entry (seconds remaining)', 30, 240, 120, 15)
    cushion_mult = st.slider('Strike cushion / estimated 1σ move', 1.0, 4.0, 2.0, 0.25)
    stop_loss = st.slider('Stop loss below entry (¢)', 2, 25, 8)
    take_profit = st.slider('Take profit above entry (¢)', 1, 15, 5)
    emergency_mult = st.slider('Emergency cushion threshold (σ)', 0.25, 2.0, 0.75, 0.25)
    max_spread = st.slider('Maximum spread (¢)', 1, 15, 5)
    qty = st.number_input('Paper contracts', 1, 50, 1)
    st.caption('One entry per interval. A bid/ask snapshot does not guarantee a fill.')

st_autorefresh(interval=10000, key='late_refresh')
now = time.time()
try:
    conn, pg = db_connect()
    init_db(conn, pg)
    state = load_state(conn, pg)
except Exception as e:
    st.error(f'Storage unavailable: {e}. Trading paused to avoid losing positions.')
    st.stop()

if not pg:
    st.warning('Local SQLite storage is temporary on Streamlit Community Cloud. Add DATABASE_URL in Streamlit Secrets for durable Supabase Postgres storage.')

market = None
market_error = None
try:
    market, start, end = find_market(now)
except Exception as e:
    market_error = str(e)

# Manage a previously locked position using ITS OWN market, not the newly selected market.
pos = state.get('position')
if pos:
    try:
        held = get_json(f'{API}/markets/{quote(pos["ticker"], safe="")}').get('market', {})
        result = str(held.get('result') or '').lower()
        if result in ('yes', 'no'):
            payout = 100.0 if result.upper() == pos['side'] else 0.0
            close_position(state, payout, 'SETTLED ' + result.upper(), now)
            save_state(conn, pg, state)
        elif result in ('', 'none'):
            book = orderbook(pos['ticker'])
            side = pos['side']
            bid = book[side]['bid']
            if bid is not None and book[side]['bid_size'] >= pos['qty']:
                reason = None
                if bid >= pos.get('take_profit_price', min(100.0, pos['entry'] + take_profit)):
                    reason = 'TAKE PROFIT'
                elif bid <= pos.get('stop_loss_price', max(0.0, pos['entry'] - stop_loss)):
                    reason = 'STOP LOSS'
                # Emergency cushion only if same contract is still trading.
                if reason is None and now < pos['close_ts']:
                    try:
                        spot, sigma = btc_spot_and_volatility()
                        strike = pos['strike']
                        signed = (spot-strike) if side == 'YES' else (strike-spot)
                        remaining = max(1, pos['close_ts']-now)
                        cushion = signed/(spot*sigma*math.sqrt(remaining/60))
                        if cushion < emergency_mult:
                            reason = 'EMERGENCY STRIKE CUSHION'
                    except Exception:
                        pass  # stale proxy must never force an emergency sale
                if reason and now < pos['close_ts']:
                    close_position(state, bid, reason, now, fee_estimate(bid, pos['qty']))
                    save_state(conn, pg, state)
            if state['position']:
                st.info('Open position: ' + pos['side'] + ' ' + pos['ticker'] +
                        f' | locked fill {pos["entry"]:.1f}¢ | bid {bid if bid is not None else "N/A"}¢ | target {pos.get("take_profit_price", pos["entry"]+take_profit):.1f}¢ | stop {pos.get("stop_loss_price", pos["entry"]-stop_loss):.1f}¢')
                if now >= pos['close_ts']:
                    st.warning('Market closed; awaiting official Kalshi settlement result. Position is preserved.')
        else:
            st.warning('Unrecognized settlement result; preserving open position.')
    except Exception as e:
        st.warning(f'Could not update held position: {e}. Position preserved; no new entries.')

if market_error:
    st.error('Kalshi market lookup failed: ' + market_error)
elif market is None:
    st.info('No currently active KXBTC15M market found. Waiting for next refresh.')
else:
    ticker = market['ticker']
    remain = end - now
    strike_raw = market.get('floor_strike')
    try:
        strike = float(strike_raw) if strike_raw is not None else None
    except (ValueError, TypeError):
        strike = None
    st.subheader('Current market')
    st.write(f'**{ticker}** · {remain:.0f}s until close · strike: {f"${strike:,.2f}" if strike else "Unavailable"}')
    try:
        quotes = orderbook(ticker)
        spot, sigma = btc_spot_and_volatility()
        st.caption('BTC spot/volatility: Coinbase BTC-USD proxy. This is NOT guaranteed to match Kalshi’s official settlement price.')
        c1,c2,c3 = st.columns(3)
        c1.metric('Coinbase BTC spot', f'${spot:,.2f}')
        c2.metric('YES ask / bid', f'{quotes["YES"]["ask"]}¢ / {quotes["YES"]["bid"]}¢')
        c3.metric('NO ask / bid', f'{quotes["NO"]["ask"]}¢ / {quotes["NO"]["bid"]}¢')
        if all(quotes[side]['bid'] is None and quotes[side]['ask'] is None for side in ('YES', 'NO')):
            st.warning('Kalshi returned an empty order book for this contract. No entry is possible until real bids appear.')
        rows = []
        for side in ('YES', 'NO'):
            q = quotes[side]
            ask, bid = q['ask'], q['bid']
            signed = (spot-strike) if side == 'YES' else (strike-spot) if strike is not None else None
            if strike is None:
                signed = None
            one_sigma = spot*sigma*math.sqrt(max(1,remain)/60)
            cushion = signed/one_sigma if signed is not None and one_sigma > 0 else None
            spread = ask-bid if ask is not None and bid is not None else None
            checks = {
                'time': min_remaining <= remain <= max_remaining*60,
                'price': ask is not None and min_ask <= ask <= max_ask,
                'strike': cushion is not None and cushion >= cushion_mult,
                'spread': spread is not None and 0 <= spread <= max_spread,
                'depth': q['ask_size'] >= qty and q['bid_size'] >= qty,
                'fresh': market.get('status') in ('active', 'open'),
                'unused': ticker not in state['used'] and state['position'] is None,
            }
            rows.append({'side': side, 'ask': ask, 'bid': bid, 'spread': spread,
                         'strike distance $': round(signed,2) if signed is not None else None,
                         'cushion σ': round(cushion,2) if cushion is not None else None,
                         'entry allowed': all(checks.values()), 'failed checks': ', '.join(k for k,v in checks.items() if not v)})
            if auto and all(checks.values()) and state['position'] is None:
                fee = fee_estimate(ask, qty)
                cost = ask*qty/100 + fee
                if state['balance'] >= cost:
                    state['position'] = {'ticker': ticker, 'side': side, 'entry': ask, 'qty': int(qty),
                        'entry_fee': fee, 'strike': strike, 'close_ts': end,
                        'opened_at': datetime.fromtimestamp(now,timezone.utc).isoformat(),
                        'entry_cushion': round(cushion,3),
                        'take_profit_price': round(min(100.0, ask + take_profit), 4),
                        'stop_loss_price': round(max(0.0, ask - stop_loss), 4)}
                    state['balance'] = round(state['balance'] - cost,4)
                    state['used'].append(ticker)
                    state['event'] = f'PAPER BUY {side} {ticker} @ {ask:.1f}¢'
                    save_state(conn, pg, state)
                    st.success(state['event'])
                else:
                    st.warning('Insufficient paper balance')
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if not auto:
            st.caption('Automatic entries OFF. Enable in sidebar to begin paper simulation.')
    except Exception as e:
        st.error(f'Market data unavailable: {e}. No entry will be made.')

# Large, phone-friendly position panel: the fill and its targets remain fixed.
st.divider()
st.subheader('🔒 Paper trade tracker')
active = state.get('position')
if active:
    st.success(f'🔒 LOCKED {active["side"]} PAPER TRADE — {active["ticker"]}')
    entry_price = float(active['entry'])
    target_price = float(active.get('take_profit_price', min(100.0, entry_price + take_profit)))
    stop_price = float(active.get('stop_loss_price', max(0.0, entry_price - stop_loss)))
    live_bid = None
    try:
        held_quotes = orderbook(active['ticker'])
        live_bid = held_quotes[active['side']]['bid']
    except Exception:
        pass
    left, right = st.columns(2)
    left.metric('🔒 LOCKED ENTRY', f'{entry_price:.1f}¢')
    right.metric('🎯 TAKE PROFIT', f'{target_price:.1f}¢')
    left.metric('🛑 STOP LOSS', f'{stop_price:.1f}¢')
    right.metric('📈 CURRENT BID', f'{live_bid:.1f}¢' if live_bid is not None else 'Unavailable')
    if live_bid is not None:
        mark = (live_bid - entry_price) * int(active['qty']) / 100 - float(active.get('entry_fee', 0)) - fee_estimate(live_bid, int(active['qty']))
        st.metric('Estimated P&L if exited at displayed bid', f'${mark:+.2f}')
    else:
        st.warning('Bid unavailable. No executable exit price can be estimated.')
    st.caption(f'Locked at {active.get("opened_at", "unknown time")} UTC · {active["qty"]} paper contract(s). '
               'Entry and target prices stay fixed even when the next interval opens. '
               'Stops and targets are not guaranteed fills; monitoring requires an active session.')
elif state.get('trades'):
    last = state['trades'][-1]
    st.info(f'✅ LAST TRADE CLOSED — {last["side"]} · {last["exit_reason"]}')
    left, right = st.columns(2)
    left.metric('🔒 LOCKED ENTRY', f'{float(last["entry"]):.1f}¢')
    right.metric('EXIT PRICE', f'{float(last["exit"]):.1f}¢')
    left.metric('🎯 ORIGINAL TARGET', f'{float(last.get("take_profit_price", min(100.0, last["entry"] + take_profit))):.1f}¢')
    right.metric('NET REALIZED P&L', f'${float(last["net_pnl"]):+.2f}')
    st.caption('WAITING FOR NEXT ENTRY · Previous trade is saved in history.')
else:
    st.info('⏳ WAITING FOR ENTRY — No paper trade is locked yet.')
    st.caption('When a trade opens, its actual simulated fill, take-profit, stop-loss and live bid will appear here.')

st.divider()
st.subheader('Paper account')
a,b,c = st.columns(3)
a.metric('Available cash', f'${state["balance"]:,.2f}')
b.metric('Closed trades', len(state['trades']))
c.metric('Realized net P&L', f'${sum(t["net_pnl"] for t in state["trades"]):+.2f}')
st.caption('Last event: ' + state.get('event','—'))
if state['trades']:
    st.dataframe(pd.DataFrame(state['trades'][::-1]), use_container_width=True, hide_index=True)
    st.download_button('Download trade history CSV', pd.DataFrame(state['trades']).to_csv(index=False),
                       file_name='kalshi_late_paper_trades.csv', mime='text/csv')
if state['position']:
    st.warning('Open position cannot be reset. It will remain until a simulated exit or official settlement.')
with st.expander('How this bot works / important limitations'):
    st.markdown('''- **Hybrid exit:** sell at the best displayed bid for +5¢ take profit, -8¢ stop loss, or emergency strike-cushion breach; otherwise wait for official settlement. All thresholds adjustable.
- **Risk:** stops can fail due to missing bids, slippage, market closure, or session suspension. At 80¢, the maximum settlement loss is 80¢ plus fees per contract.
- **Strike cushion:** uses Coinbase one-minute return volatility as a rough risk proxy, **not a calibrated win probability**. A 2σ cushion does not imply an 80% or 95% win chance.
- **Data:** quotes are live public snapshots, not executable fills. Kalshi may use a different reference price for settlement than Coinbase.
- **Persistence:** add a Supabase Postgres `DATABASE_URL` in Streamlit Secrets. Without it, local SQLite may be wiped by Streamlit Cloud.
- **Execution:** Streamlit refreshes while a browser session is active. Closing your phone stops monitoring; when reopened, saved positions are checked and official settlements reconciled if available. **No real orders are placed.**''')
conn.close()
