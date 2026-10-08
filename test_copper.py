import yfinance as yf
# 试铜ETF
for sym in ['CPER', 'COPX', 'CZN', 'JJCTF']:
    try:
        df = yf.Ticker(sym).history(period='5d')
        if not df.empty:
            print(f'{sym}: {df["Close"].iloc[-1]:.2f}')
        else:
            print(f'{sym}: 空')
    except Exception as e:
        print(f'{sym}: {e}')

# 试 CFTC 铜持仓相关
print('---')
# 试找铜精矿TC的代理
for sym in ['^SPGSCI', 'GC=F', 'SI=F']:
    try:
        df = yf.Ticker(sym).history(period='5d')
        if not df.empty:
            print(f'{sym}: {df["Close"].iloc[-1]:.2f}')
    except Exception as e:
        print(f'{sym}: {e}')
