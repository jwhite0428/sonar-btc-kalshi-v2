"""Sonar BTC / Kalshi 15m — mobile-friendly Streamlit paper dashboard.
No trading credentials, no live order execution.
"""
from datetime import datetime, timezone
import math
import time
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='SONAR · BTC / Kalshi 15m', page_icon='📈', layout='wide')
st.markdown('''<style>
.stApp {background:#080e11;color:#e8f4ec} .block-container{padding-top:1.1rem;max-width:1200px}
[data-testid="stMetric"]{background:#101c20;border:1px solid #263c3b;border-radius:9px;padding:12px}
h1,h2,h3 {letter-spacing:-.04em} div.stButton>button {border-color:#658b35}
</style>''', unsafe_allow_html=True)
HEAD={'User-Agent':'SonarStreamlitPaper/1.0','Accept':'application/json'}

@st.cache_data(ttl=10,show_spinner=False)
def candles(granularity):
    r=requests.get('https://api.exchange.coinbase.com/products/BTC-USD/candles', params={'granularity':granularity}, headers=HEAD,timeout=12)
    r.raise_for_status()
    data=r.json()
    if not isinstance(data,list) or not data: raise ValueError('No Coinbase candles')
    df=pd.DataFrame(data,columns=['ts','low','high','open','close','volume'])
    df=df.sort_values('ts').reset_index(drop=True)
    df['date']=pd.to_datetime(df['ts'],unit='s',utc=True)
    return df

@st.cache_data(ttl=6,show_spinner=False)
def last_price():
    r=requests.get('https://api.exchange.coinbase.com/products/BTC-USD/ticker',headers=HEAD,timeout=12)
    r.raise_for_status()
    return float(r.json()['price'])

@st.cache_data(ttl=8,show_spinner=False)
def kalshi_market():
    r=requests.get('https://external-api.kalshi.com/trade-api/v2/markets', params={'series_ticker':'KXBTC15M','status':'open','limit':100},headers=HEAD,timeout=12)
    r.raise_for_status()
    ms=r.json().get('markets') or []
    now=datetime.now(timezone.utc)
    options=[]
    for m in ms:
        try:
            close=datetime.fromisoformat(m['close_time'].replace('Z','+00:00'))
            opened=datetime.fromisoformat(m['open_time'].replace('Z','+00:00')) if m.get('open_time') else now
            if close>now>=opened and m.get('status','').lower() in ('active','open'):
                options.append((close,m))
        except (ValueError,TypeError,KeyError): pass
    return min(options,key=lambda t:t[0])[1] if options else None

def q(m,side,action):
    if m is None:return None
    name=f'{side}_{action}'
    try:
        if m.get(name+'_dollars') is not None:return round(float(m[name+'_dollars'])*100,2)
        v=m.get(name)
        return float(v) if isinstance(v,(int,float)) else None
    except (TypeError,ValueError):return None

def strike(m):
    if not m:return None
    for key in ('floor_strike','cap_strike'):
        try:
            if m.get(key) is not None:return float(m[key])
        except (ValueError,TypeError):pass
    return None

def ema(values,n):return pd.Series(values).ewm(span=n,adjust=False).mean()
def rsi(values,n=14):
    d=pd.Series(values).diff();up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean();dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100 - 100/(1+up/dn.replace(0,1e-9))

def patterns(df):
    if len(df)<35:return []
    c=df['close'].astype(float).reset_index(drop=True);o=df['open'].astype(float).reset_index(drop=True)
    hi=df['high'].astype(float).reset_index(drop=True);lo=df['low'].astype(float).reset_index(drop=True)
    a=[];rng=max(float(hi.iloc[-1]-lo.iloc[-1]),1e-9)
    if abs(float(c.iloc[-1]-o.iloc[-1]))/rng<.12:a.append(('Doji','Neutral', 'Small real body relative to candle range'))
    # Heuristic structure detection, never a calibrated win rate.
    recent=c.iloc[-20:];last=c.iloc[-7:]
    prior=c.iloc[-20:-7]
    rise=(prior.iloc[-1]-prior.iloc[0])/max(abs(prior.iloc[0]),1)
    pull=(last.iloc[-1]-last.iloc[0])/max(abs(last.iloc[0]),1)
    if rise>.0015 and -.0015<pull<0:a.append(('Bull flag candidate','Bullish','Rise followed by modest pullback'))
    if rise<-.0015 and 0<pull<.0015:a.append(('Bear flag candidate','Bearish','Drop followed by modest bounce'))
    if abs(float(hi.iloc[-5:-1].max()-hi.iloc[-15:-7].max()))/float(c.iloc[-1])<.0008 and float(c.iloc[-1])<float(hi.iloc[-5:-1].max())*.9995:a.append(('Double-top candidate','Bearish','Two similar recent highs'))
    if abs(float(lo.iloc[-5:-1].min()-lo.iloc[-15:-7].min()))/float(c.iloc[-1])<.0008 and float(c.iloc[-1])>float(lo.iloc[-5:-1].min())*1.0005:a.append(('Double-bottom candidate','Bullish','Two similar recent lows'))
    return a or [('No clear pattern','Neutral','No simple pattern passed its heuristic filter')]

def render_chart(df,show_levels,show_emas):
    fig=go.Figure(go.Candlestick(x=df.date,open=df.open,high=df.high,low=df.low,close=df.close,
        increasing_line_color='#b6f64b',decreasing_line_color='#ff6681',name='BTC/USD'))
    if show_emas:
        fig.add_trace(go.Scatter(x=df.date,y=ema(df.close,9),name='EMA 9',line={'color':'#78d9e5','width':1.5}))
        fig.add_trace(go.Scatter(x=df.date,y=ema(df.close,21),name='EMA 21',line={'color':'#ffb44b','width':1.5}))
    if show_levels:
        tail=df.tail(40)
        fig.add_hline(y=float(tail.high.max()),line_dash='dash',line_color='#df9b5c',annotation_text='Resistance')
        fig.add_hline(y=float(tail.low.min()),line_dash='dash',line_color='#8fcf67',annotation_text='Support')
    fig.update_layout(height=410,margin=dict(l=4,r=4,t=20,b=4),paper_bgcolor='#080e11',plot_bgcolor='#0b1418',font_color='#dbe5df',
        xaxis_rangeslider_visible=False,legend=dict(orientation='h',y=1.13),xaxis=dict(gridcolor='#20302e'),yaxis=dict(gridcolor='#20302e'))
    st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})

st.title('SONAR / BTC–USD')
st.caption('LIVE MARKET WORKSPACE · Kalshi BTC 15-minute decision engine · paper trades only')
with st.sidebar:
    st.header('Chart')
    timeframe=st.selectbox('Timeframe',['1m','5m','15m','1h'],index=0)
    levels=st.checkbox('Support / resistance',True)
    emas=st.checkbox('EMA 9 / 21',True)
    st.header('Late-entry settings')
    min_entry=st.number_input('Minimum ask (¢)',min_value=1,max_value=99,value=80)
    max_entry=st.number_input('Maximum ask (¢)',min_value=1,max_value=99,value=96)
    max_seconds=st.number_input('Maximum seconds remaining',min_value=15,max_value=900,value=180)
    min_gap=st.number_input('Minimum BTC–strike gap ($)',min_value=0,max_value=10000,value=100)
    tp=st.number_input('Take profit: bid (¢)',min_value=1,max_value=99,value=97)
    sl=st.number_input('Stop loss: bid (¢)',min_value=1,max_value=99,value=70)
    qty=st.number_input('Paper contracts',min_value=1,max_value=1000,value=10)
    st.caption('The Coinbase price may differ from Kalshi’s settlement reference. Distances and trend filters are informational proxies.')

if 'paper_positions' not in st.session_state:st.session_state.paper_positions=[]
if 'paper_history' not in st.session_state:st.session_state.paper_history=[]

@st.fragment(run_every='10s')
def dashboard():
    d={ '1m':60,'5m':300,'15m':900,'1h':3600}
    try:
        df=candles(d[timeframe]);px=last_price()
    except Exception as e:
        st.error('Coinbase market data currently unavailable: '+str(e));return
    vals=df.close.astype(float);e9=float(ema(vals,9).iloc[-1]);e21=float(ema(vals,21).iloc[-1]);strength=float(rsi(vals).iloc[-1])
    trend='UP' if e9>e21 else 'DOWN' if e9<e21 else 'FLAT'
    c1,c2,c3,c4=st.columns(4)
    c1.metric('BTC/USD',f'${px:,.2f}');c2.metric('EMA trend',trend);c3.metric('RSI 14',f'{strength:.1f}');c4.metric('Chart interval',timeframe)
    render_chart(df,levels,emas)
    with st.expander('Pattern playbook · heuristic scanner',expanded=True):
        for title,direction,reason in patterns(df):st.write(f'**{title}** · {direction} — {reason}')
        st.caption('Pattern labels are heuristic detections, not probability forecasts or trading recommendations.')
    st.subheader('KALSHI / BTC 15-MIN LIVE CONTRACT')
    try:m=kalshi_market();error=None
    except Exception as e:m=None;error=str(e)
    if not m:
        st.warning('Kalshi data unavailable: '+error if error else 'No currently open KXBTC15M contract was returned.')
        st.info('Decision: NO TRADE — live contract data required.');return
    close=datetime.fromisoformat(m['close_time'].replace('Z','+00:00'))
    remain=max(0,int((close-datetime.now(timezone.utc)).total_seconds()))
    stk=strike(m); gap=abs(px-stk) if stk is not None else None
    yes_ask=q(m,'yes','ask');no_ask=q(m,'no','ask');yes_bid=q(m,'yes','bid');no_bid=q(m,'no','bid')
    st.caption(f"{m.get('ticker','Unknown ticker')} · {m.get('title','')} · status {m.get('status','unknown')}")
    a,b,c,d,e=st.columns(5)
    a.metric('Time remaining',f'{remain//60:02}:{remain%60:02}')
    b.metric('Market strike',f'${stk:,.2f}' if stk is not None else 'N/A')
    c.metric('BTC – strike',f'${px-stk:+,.2f}' if stk is not None else 'N/A')
    d.metric('UP bid / ask',f'{yes_bid:g}¢ / {yes_ask:g}¢' if yes_bid is not None and yes_ask is not None else 'N/A')
    e.metric('DOWN bid / ask',f'{no_bid:g}¢ / {no_ask:g}¢' if no_bid is not None and no_ask is not None else 'N/A')
    side='UP' if stk is not None and px>stk else 'DOWN' if stk is not None and px<stk else None
    ask=yes_ask if side=='UP' else no_ask if side=='DOWN' else None
    reasons=[]
    if side is None:reasons.append('Strike not available or BTC exactly at strike')
    if gap is None or gap<min_gap:reasons.append('BTC–strike distance below minimum')
    if remain<=15 or remain>max_seconds:reasons.append('Outside late-entry time window')
    if ask is None or ask<min_entry or ask>max_entry:reasons.append('Contract ask outside entry range or missing')
    if trend!=side:reasons.append('Chart EMA trend does not match side')
    if not (sl<tp):reasons.append('Stop loss must be below take profit')
    eligible=not reasons
    st.markdown(f"### {'WATCH '+side if eligible else 'NO TRADE'}")
    st.write('All selected paper-entry filters passed; not a verified edge.' if eligible else ' · '.join(reasons))
    st.caption('This is a chart-based watch signal. Kalshi settlement uses its own reference price, not necessarily Coinbase.')
    if st.button(f'Open {qty} PAPER {side} contracts at {ask}¢' if eligible else 'Paper entry unavailable',disabled=not eligible or bool(st.session_state.paper_positions),type='primary'):
        st.session_state.paper_positions.append({'ticker':m.get('ticker'),'side':side,'entry':ask,'qty':qty,'at':datetime.now(timezone.utc).isoformat()})
        st.rerun(scope='fragment')
    if st.session_state.paper_positions:
        p=st.session_state.paper_positions[0]
        matching=p['ticker']==m.get('ticker')
        bid=(yes_bid if p['side']=='UP' else no_bid) if matching else None
        st.write(f"**Open PAPER:** {p['side']} × {p['qty']} · entry {p['entry']}¢ · current bid {str(bid)+'¢' if bid is not None else 'unavailable'}")
        if bid is not None:st.metric('Unrealized mark-to-bid, before fees',f"${(bid-p['entry'])*p['qty']/100:,.2f}")
        reason=None
        if matching and bid is not None and bid>=tp:reason='TAKE PROFIT'
        elif matching and bid is not None and bid<=sl:reason='STOP LOSS'
        elif remain==0 and matching:reason='CONTRACT CLOSED — manual settlement review required'
        if reason:
            st.warning(reason+' (paper simulation; quotes are not guaranteed fills)')
        if st.button('Close paper position (at displayed bid when available)'):
            p=p.copy();p.update({'exit':bid,'reason':reason or 'MANUAL','closed_at':datetime.now(timezone.utc).isoformat()})
            st.session_state.paper_history.insert(0,p);st.session_state.paper_positions.clear();st.rerun(scope='fragment')
    if st.session_state.paper_history:
        st.subheader('Paper trade history')
        st.dataframe(pd.DataFrame(st.session_state.paper_history),use_container_width=True,hide_index=True)
    st.caption('Refreshes about every 10 seconds while this page is open. Paper positions are session-only and are not persisted after a server restart.')

dashboard()
