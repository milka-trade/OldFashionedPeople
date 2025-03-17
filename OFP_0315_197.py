import time
import threading
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import ta
import pandas as pd

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("discord_webhhok")
upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS"), os.getenv("UPBIT_SECRET"))

count_200 = 200

min15 = "minute15"
min5 = "minute5"
# srsi_value_s = 0.1
# srsi_value_e = 0.35

def send_discord_message(msg):
    """discord 메시지 전송"""
    try:
        message ={"content":msg}
        requests.post(DISCORD_WEBHOOK_URL, data=message)
    except Exception as e:
        print(f"디스코드 메시지 전송 실패 : {e}")
        time.sleep(5) 

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 0.35): "))
            max_rate = float(input("최대 수익률 (예: 1.1): "))
            srsi_value_s = float(input("srsi D 매수 시작 (예: 0.05): "))
            srsi_value_e = float(input("srsi D 매수 제한 (예: 0.4): "))
            sell_time = int(input("매도감시횟수 (예: 15): "))
            break  # 모든 입력이 성공적으로 완료되면 루프 종료
        except ValueError:
            print("잘못된 입력입니다. 다시 시도하세요.")

    return min_rate, max_rate, sell_time, srsi_value_s, srsi_value_e

# 함수 호출 및 결과 저장
min_rate, max_rate, sell_time, srsi_value_s, srsi_value_e = get_user_input()

second = 1.0
min_krw = 50_000
cut_rate = -2.0

def get_balance(ticker):
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == ticker:
                time.sleep(0.5)
                return float(b['balance']) if b['balance'] is not None else 0
            
    except (KeyError, ValueError) as e:
        print(f"get_balance/잔고 조회 오류: {e}")
        send_discord_message(f"get_balance/잔고 조회 오류: {e}")
        time.sleep(1)
        return 0
    return 0

def get_ema(ticker, interval = min5):
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count_200)
    time.sleep(0.3)

    if df is not None and not df.empty:
        df['ema'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        return df['ema'].tail(2)  # EMA의 마지막 값 반환
    
    else:
        return 0  # 데이터가 없으면 0 반환
    
def stoch_rsi(ticker, interval = min5):
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count_200)
    time.sleep(second)
     
    rsi = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    min_rsi = rsi.rolling(window=14).min()
    max_rsi = rsi.rolling(window=14).max()
        
    rsi = rsi.bfill()  # 이후 값으로 NaN 대체
    min_rsi = min_rsi.bfill()
    max_rsi = max_rsi.bfill()
        
    stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)
    stoch_rsi = stoch_rsi.replace([np.inf, -np.inf], np.nan)  # 무한대를 np.nan으로 대체
    stoch_rsi = stoch_rsi.fillna(0)  # NaN을 0으로 대체 (필요 시)

    k_period = 3  # %K 기간
    d_period = 3  # %D 기간
        
    stoch_rsi_k = stoch_rsi.rolling(window=k_period).mean()
    stoch_rsi_d = stoch_rsi_k.rolling(window=d_period).mean()

    result_df = pd.DataFrame({  # 결과를 DataFrame으로 묶어서 반환
            'StochRSI': stoch_rsi,
            '%K': stoch_rsi_k,
            '%D': stoch_rsi_d
        })
        
    return result_df.tail(3)

def get_bollinger_bands(ticker, interval = min5, window=20, std_dev=2):
    """특정 티커의 볼린저 밴드 상단 및 하단값을 가져오는 함수"""
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count_200)
    time.sleep(second)
    if df is None or df.empty:
        return None  # 데이터가 없으면 None 반환

    bollinger = ta.volatility.BollingerBands(df['close'], window=window, window_dev=std_dev)

    upper_band = bollinger.bollinger_hband().fillna(0)  
    lower_band = bollinger.bollinger_lband().fillna(0)  
    
    bands_df = pd.DataFrame({   # DataFrame으로 묶기
        'Upper_Band': upper_band,
        'Lower_Band': lower_band
    })

    return bands_df.tail(6)

def filtered_tickers(tickers):
    """특정 조건에 맞는 티커 필터링"""
    filtered_tickers = []
    
    for t in tickers:
        try:
            df = pyupbit.get_ohlcv(t, interval=min5, count=6)
            if df is None:
                print(f"[filter_tickers] 데이터를 가져올 수 없습니다. {t}")
                send_discord_message(f"[filter_tickers] 데이터를 가져올 수 없습니다: {t}")
                continue  # 다음 티커로 넘어감
            time.sleep(second)
            df_close = df['close'].values

            bands_df = get_bollinger_bands(t, interval = min5)
            upper_band = bands_df['Upper_Band'].values
            lower_band = bands_df['Lower_Band'].values
            band_diff = (upper_band - lower_band) / lower_band

            bands_df15 = get_bollinger_bands(t, interval = min15)
            upper_band15 = bands_df15['Upper_Band'].values
            lower_band15 = bands_df15['Lower_Band'].values
            band_diff15 = (upper_band15 - lower_band15) / lower_band15

            band_diff_margin = 0.015
            band_diff_15_margin = 0.015
            # srsi_value15_e = 0.4
            is_increasing_5 = band_diff[-1] > band_diff_margin
            is_increasing_15 = band_diff15[-1] > band_diff_15_margin
            is_increasing = is_increasing_15 and is_increasing_5
            count_below_lower_band = sum(1 for i in range(len(lower_band15)) if df_close[i] < lower_band15[i] * 1.005)
            low_boliinger = count_below_lower_band >= 1
            
            slopes = np.diff(lower_band)
            slopes_2 = (abs(slopes[-2]) / lower_band[-3]) * 100
            slopes_1 = (abs(slopes[-1]) / lower_band[-2]) * 100
            low_band_slope_decreasing = slopes_2 > slopes_1

            stoch_Rsi = stoch_rsi(t, interval = min5)
            srsi_k = stoch_Rsi['%K'].values
            srsi_d = stoch_Rsi['%D'].values
            srsi_d_rising = srsi_d[-1] < srsi_k[-1] and (srsi_value_s <= srsi_d[-1] <= srsi_value_e) #and (srsi_d[-2] > srsi_k[-2] or srsi_d[-3] > srsi_k[-3])
            
            # srsi_diff = abs(srsi_k - srsi_d)
            # srsi_increasing = srsi_diff[1] <= srsi_diff[2] 
            # srsi_diff = abs((srsi_k[-3] - srsi_d[-3])) <= abs((srsi_k[-2] - srsi_d[-2])) <= abs((srsi_k[-1] - srsi_d[-1]))
                        
            # cur_price = pyupbit.get_current_price(t)
            # test_time = datetime.now().strftime('%m/%d %H:%M:%S')
            
            filtering_message = f"<<{t}>>\n"
            filtering_message += f"[cond1: {is_increasing}] band_diff15: {is_increasing_15} / {band_diff15[-1]:,.3f} > {band_diff_15_margin} / band_diff: {is_increasing_5} {band_diff[-1]:,.3f} > {band_diff_margin} \n"
            filtering_message += f"[cond2: {low_boliinger}] LowBoliinger: {low_boliinger} / LB * 0.5%: {lower_band[-1] * 1.005:,.3f} > df_close: {df_close[-1]:,.3f} \n"
            filtering_message += f"[cond3: {srsi_d_rising}] srsi_d: {srsi_d_rising} / {srsi_value_s} < srsi_d: {srsi_d[-2]:,.3f} >> {srsi_d[-1]:,.3f} < {srsi_value_e} / srsi_k: {srsi_k[-2]:,.3f} >> {srsi_k[-1]:,.3f} \n"
            filtering_message += f"[test4: {low_band_slope_decreasing}] LBandSslopes: {low_band_slope_decreasing} / {slopes_2:,.3f} >> {slopes_1:,.3f} \n"
            
            filtering_message4 = f"[cond4: {low_band_slope_decreasing}] LBandSslopes: {low_band_slope_decreasing} / {slopes_2:,.3f} >> {slopes_1:,.3f} \n"

            # print(filtering_message)
            if is_increasing_15 :
                print(filtering_message)
                if is_increasing_5 :
                    # print(filtering_message)
                    if low_boliinger :
                        # print(filtering_message)
                        if srsi_d_rising :
                            # print(filtering_message)
                            if low_band_slope_decreasing :
                            # print(filtering_message)
                                # if srsi_increasing :
                                    print(filtering_message4)
                                    send_discord_message(filtering_message)
                                    filtered_tickers.append(t)
                
        except (KeyError, ValueError) as e:
            send_discord_message(f"filtered_tickers/Error processing ticker {t}: {e}")
            time.sleep(5) 

    return filtered_tickers

def get_best_ticker():
    selected_tickers = ["KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-HBAR", "KRW-XLM", "KRW-DOGE"]
    balances = upbit.get_balances()
    held_coins = []

    for b in balances:
        if float(b['balance']) > 0:  # 보유량이 0보다 큰 경우
            ticker = f"KRW-{b['currency']}"  # 현재가 조회를 위한 티커 설정
            held_coins.append(ticker)  # "KRW-코인명" 형태로 추가
    
    try:
        all_tickers = pyupbit.get_tickers(fiat="KRW")
        filtering_tickers = []

        for ticker in all_tickers:
            if ticker in selected_tickers and ticker not in held_coins:

                df_15 = pyupbit.get_ohlcv(ticker, interval=min15, count=3)
                time.sleep(second)
                df_open_0 = df_15['open'].iloc[0]
                df_open_1 = df_15['open'].iloc[1]
                df_open_2 = df_15['open'].iloc[2]

                df_high_0 = df_15['high'].iloc[0]
                df_high_1 = df_15['high'].iloc[1]
                df_high_2 = df_15['high'].iloc[2]
                
                candle_cond0 = df_high_0 < df_open_0 * 1.02
                candle_cond1 = df_high_1 < df_open_1 * 1.02
                candle_cond2 = df_high_2 < df_open_2 * 1.02

                # cur_price = pyupbit.get_current_price(ticker)

                if candle_cond0 and candle_cond1 and candle_cond2 :
                    filtering_tickers.append(ticker)
                            
    except (KeyError, ValueError) as e:
        send_discord_message(f"get_best_ticker/티커 조회 중 오류 발생: {e}")
        time.sleep(second) 
        return None

    filtered_list = filtered_tickers(filtering_tickers)
    if len(filtered_list) > 0 :
        filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
        send_discord_message(f"{filtered_time} [{filtered_list}]")
    
    if len(filtered_list) == 1:
        return filtered_list[0]  # 티커가 1개인 경우 해당 티커 반환
    
    bestC = None  # 초기 최고 코인 초기화
    low_srsi_d = float('inf')  # 가장 낮은 srsi 'D' 값 초기화

    for ticker in filtered_list:   # 조회할 코인 필터링
        stoch_Rsi = stoch_rsi(ticker, interval = min5)
        srsi_d = stoch_Rsi['%D'].values

        # srsi 'D' 값이 존재하는지 체크
        if len(srsi_d) == 0:
            continue

        current_srsi_d = srsi_d[-1]  # 가장 최근 'D' 값

        if current_srsi_d < low_srsi_d:  # 현재 'D' 값이 가장 낮으면 업데이트
            bestC = ticker
            low_srsi_d = current_srsi_d

        time.sleep(second)  # API 호출 간 대기
    return bestC   # 가장 낮은 srsi 'D' 값을 가진 코인 반환

def trade_buy(ticker):
    
    krw = get_balance("KRW")
    max_retries = 5
    # buy_size = min(trade_Quant, krw*0.9995)
    buy_size = krw*0.9995
    cur_price = pyupbit.get_current_price(ticker)    
    attempt = 0 
       
    stoch_Rsi = stoch_rsi(ticker, interval = min5)
    srsi_k = stoch_Rsi['%K'].values
    srsi_d = stoch_Rsi['%D'].values
    srsi_buy = srsi_d[2] < srsi_k[2] and (srsi_value_s <= srsi_d[2] <= srsi_value_e) and srsi_k[1] < srsi_k[2]
    last_ema = get_ema(ticker, interval = min5).iloc[1]

    if krw >= min_krw :
        while attempt < max_retries:
            print(f"[가격 확인 중]: {ticker} srsi_buy: {srsi_buy} / 현재가: {cur_price:,.2f} / 시도: {attempt} - 최대: {max_retries}")
            
            if srsi_buy and cur_price < last_ema :
                buy_attempts = 3
                for i in range(buy_attempts):
                    try:
                        buy_order = upbit.buy_market_order(ticker, buy_size)
                        send_discord_message(f"매수 성공: {ticker} / 현재가 :{cur_price:,.2f} / {srsi_value_s} < srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} < srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f} < {srsi_value_e}")
                        return buy_order

                    except (KeyError, ValueError) as e:
                        print(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                        send_discord_message(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                        time.sleep(5 * (i + 1)) 

                return "Buy order failed", None
            else:
                attempt += 1  # 시도 횟수 증가
                time.sleep(2)

        print(f"[매수 실패]: {ticker} / 현재가: {cur_price:,.2f} / {srsi_value_s} < srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} < srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f} < {srsi_value_e}")
        send_discord_message(f"[매수 실패]: {ticker} / 현재가: {cur_price:,.2f} / {srsi_value_s} < srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} < srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f} < {srsi_value_e}")
        return "Price not in range after max attempts", None
            
def trade_sell(ticker):
    currency = ticker.split("-")[1]
    buyed_amount = get_balance(currency)
    
    avg_buy_price = upbit.get_avg_buy_price(currency)
    cur_price = pyupbit.get_current_price(ticker)
    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0  # 수익률 계산

    df = pyupbit.get_ohlcv(ticker, interval = min5, count = 6)
    time.sleep(second)
    df_close = df['close'].values

    bands_df = get_bollinger_bands(ticker, interval = min5)
    up_Bol = bands_df['Upper_Band'].values
    count_upper_band = sum(1 for i in range(len(up_Bol)) if up_Bol[i] < df_close[i] )
    upper_boliinger = count_upper_band >= 1

    stoch_Rsi = stoch_rsi(ticker, interval = min5)
    srsi_k = stoch_Rsi['%K'].values
    srsi_d = stoch_Rsi['%D'].values
    
    upper_price = (upper_boliinger and srsi_d[2] >= 0.9) or (srsi_d[2] >= 0.99) or (srsi_d[2] >= 0.75 and srsi_d[2] > srsi_k[2])
    middle_price = srsi_d[2] >= 0.5 and srsi_d[2] > srsi_k[2]
    cut_price = middle_price or srsi_d[2] >= 0.99

    max_attempts = sell_time
    attempts = 0

    cut_time = datetime.now()
    cut_start = cut_time.replace(hour=8, minute=55, second=00, microsecond=0)
    cut_end = cut_time.replace(hour=9, minute=1, second=55, microsecond=0)

    if cut_start <= cut_time <= cut_end:      # 매도 제한시간이면
        if cut_price :
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            print(f"[장시작전매도]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
            send_discord_message(f"[장시작전매도]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
        else:
            time.sleep(1)
            return None  

    else:
        if profit_rate >= min_rate:
            while attempts < max_attempts:       
                print(f"[{ticker}] / [매도시도 {attempts + 1} / {max_attempts}] / 수익률: {profit_rate:.2f}% / upper_price : {upper_price}")

                if profit_rate >= max_rate or upper_price :
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    print(f"[!!목표가 달성!!]:[{ticker}] / 수익률: {profit_rate:.2f}%  / 현재가: {cur_price:,.1f} upper_price: {upper_price} / 0.85 < srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} < srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                    send_discord_message(f"[!!목표가 달성!!]: [{ticker}] / 수익률: {profit_rate:.2f}%  / 현재가: {cur_price:,.1f} upper_price: {upper_price} / 0.85 < srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} < srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                    return sell_order

                else:
                    time.sleep(second)
                attempts += 1  # 조회 횟수 증가
                
            if middle_price:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                print(f"[m_price 도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                send_discord_message(f"[m_price 도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                return sell_order   
            else:
                # print(f"[m_price 미도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                send_discord_message(f"[m_price 미도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f} > srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                return None
        else:
            if profit_rate < cut_rate:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                print(f"[손절_CutRate]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f}< srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
                send_discord_message(f"[손절_CutRate]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[1]:,.2f} -> {srsi_d[2]:,.2f}< srsi_k: {srsi_k[1]:,.2f} -> {srsi_k[2]:,.2f}")
            else:
                return None  

def send_profit_report():
    first_run = True  # 처음 실행 여부를 체크하는 변수

    while True:
        try:
            now = datetime.now()  # 현재 시간을 루프 시작 시마다 업데이트
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            time_until_next_hour = (next_hour - now).total_seconds()
            # report_time = datetime.now().strftime('%m/%d %H:%M:%S')
            report_message = f" 현재 수익률 보고서:\n"
            balances = upbit.get_balances()

            # balances가 리스트인지 확인
            if isinstance(balances, list):
                for b in balances:
                    # b가 딕셔너리인지 확인
                    if isinstance(b, dict) and 'currency' in b:
                        if b['currency'] in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                            continue

                        ticker = b['currency']  # 티커를 currency로 설정
                        buyed_amount = get_balance(ticker)  # get_balance 함수 사용

                        if buyed_amount > 0:
                            avg_buy_price = float(b['avg_buy_price'])
                            cur_price = pyupbit.get_current_price(f"KRW-{ticker}")
                            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0

                            stoch_Rsi = stoch_rsi(f"KRW-{ticker}", interval=min5)
                            srsi_k = stoch_Rsi['%K'].values
                            srsi_d = stoch_Rsi['%D'].values

                            report_message += f"[{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.2f} / 보유량: {buyed_amount:.2f} / 평균 매수 가격: {avg_buy_price:.2f} \n"

                            if len(srsi_d) > 2 and len(srsi_k) > 2 :
                                report_message += f"srsi_d: {srsi_d[1]:,.3f} -> {srsi_d[2]:,.3f} / srsi_k: {srsi_k[1]:,.3f} -> {srsi_k[2]:,.3f} \n \n"
                    
                            else:
                                report_message += "RSI 데이터가 충분하지 않습니다.\n"
                # 보고서 전송
                send_discord_message(report_message)

                # 첫 실행 이후 대기
                if first_run:
                    first_run = False  # 첫 실행 후 변경
                else:
                    time.sleep(time_until_next_hour)  # 다음 정시까지 대기

            else:
                print("balances는 리스트가 아닙니다.")
                send_discord_message("balances는 리스트가 아닙니다.")
                time.sleep(5)

        except (KeyError, ValueError) as e:
            print(f"send_profit_report/수익률 보고 중 오류 발생: {e}")
            send_discord_message(f"send_profit_report/수익률 보고 중 오류 발생: {e}")
            time.sleep(5)
            
trade_start = datetime.now().strftime('%m/%d %H:%M:%S')  # 시작시간 기록
print(f'{trade_start} trading start')

profit_report_thread = threading.Thread(target=send_profit_report)  # 수익률 보고 쓰레드 시작
profit_report_thread.daemon = True  # 메인 프로세스 종료 시 함께 종료되도록 설정
profit_report_thread.start()

def selling_logic():
    while True:
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] not in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                        ticker = f"KRW-{b['currency']}"
                        trade_sell(ticker)
                time.sleep(second)

        except Exception as e:
            print(f"selling_logic / 에러 발생: {e}")
            send_discord_message(f"selling_logic / 에러 발생: {e}")
            time.sleep(5)

def buying_logic():
    while True:
        try:
            stopbuy_time = datetime.now()
            restricted_start = stopbuy_time.replace(hour=8, minute=50, second=0, microsecond=0)
            restricted_end = stopbuy_time.replace(hour=9, minute=10, second=0, microsecond=0)
            
            if restricted_start <= stopbuy_time <= restricted_end:  # 매수 제한 시간 체크
                time.sleep(60) 
                continue
            
            else:  # 매수 금지 시간이 아닐 때
                krw_balance = get_balance("KRW")  # 현재 KRW 잔고 조회
                if krw_balance > min_krw: 
                    best_ticker = get_best_ticker()

                    if best_ticker:
                        buy_time = datetime.now().strftime('%m/%d %H:%M:%S')
                        send_discord_message(f"[{buy_time}] 선정코인: [{best_ticker}]")
                        result = trade_buy(best_ticker)
                        
                        if result:
                            time.sleep(60)
                        else:
                            time.sleep(1)
                    else:
                        time.sleep(1)

                else:
                    time.sleep(60)

        except (KeyError, ValueError) as e:
            print(f"buying_logic / 에러 발생: {e}")
            send_discord_message(f"buying_logic / 에러 발생: {e}")
            time.sleep(5)

# 매도 쓰레드 생성
selling_thread = threading.Thread(target = selling_logic)
selling_thread.start()

# 매수 쓰레드 생성
buying_thread = threading.Thread(target = buying_logic)
buying_thread.start()