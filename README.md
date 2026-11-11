# SONAR BTC + Kalshi 15-Min · Streamlit V3

**This is a Streamlit Community Cloud replacement upgrade for the existing `sonar-btc-kalshi-v2` repository.** No new repo is needed.

## Upload from iPhone

1. Unzip `Sonar_BTC_Kalshi_Streamlit_V3_iPhone.zip` in iPhone Files.
2. In GitHub open the existing `sonar-btc-kalshi-v2` repository on the `main` branch.
3. Replace **root** `streamlit_app.py` with the supplied `streamlit_app.py` using GitHub file Edit (paste contents) or upload/commit replacement.
4. Replace **root** `requirements.txt` with the supplied `requirements.txt` using Edit/Commit, or replace with the uploaded file.
5. Streamlit Community Cloud generally redeploys after the push. Refresh your existing app. If not, open **Manage app → Reboot**.
6. Do not upload the ZIP or nest these files inside `templates/`. Old `app.py` and the Flask `templates` directory may remain; the deployed entrypoint remains **`streamlit_app.py`**.

## Changes

- New high-contrast tile styling and iPhone-first 2-column cards, with responsive wider layout.
- Three tabs: chart, pattern scanner, paper-trade history; cleaner ~330 px chart.
- EMA9/21, RSI14, ATR and rule-based structure scanning: doji, impulse candle, bull/bear flags, double top/bottom, head & shoulders/inverse, ascending/descending/symmetrical triangles.
- All pattern-fit numbers are *rule-match scores*, **not** calibrated probability of winning.
- Kalshi KXBTC15M market title, strike, expiry countdown, UP (YES) / DOWN (NO) bid/ask, and entry gate explanations.
- Configurable entry price band, remaining seconds, minimum BTC-to-strike gap, maximum bid/ask spread, optional RSI trend agreement, TP/SL.
- Paper positions are marked against market *bid* and automatically simulated as closed on displayed bid crossing TP/SL; settled markets use published result to simulate payout. These are **not guaranteed executable trades**, and exclude fees/slippage.

## Important limitations

- Coinbase spot pricing is **not** the official Kalshi settlement reference. For strike distance, this app uses a proxy, and late-entry contracts can still lose. Values may differ near expiry.
- Orders are NEVER sent to Kalshi. No API keys required. This is not a verified profitable strategy.
- This is a polling dashboard (approximately 10-second refresh while open), not an always-on worker. Brief quote movements between polls can be missed.
- Paper positions and history live in `st.session_state` and can be lost on server reboot, user session expiration, or app reconnection. The simulated exit price is the currently displayed bid, not guaranteed fill price; calculations are before fees, and do not model spread-induced slippage.
- Public Coinbase/Kalshi endpoints can be temporarily slow or unavailable; the app blocks new entries where live market quotes are missing. It cannot guarantee every market's strike is present.
- Do not commit any trading passwords, keys, or tokens to a public GitHub repository.
