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
            min_rate = float(input("최소 수익률 (예: 0.3): "))
            max_rate = float(input("최대 수익률 (예: 1.5): "))
            srsi_value_s = float(input("srsi D 매수 시작 (예: 0.1): "))
            srsi_value_e = float(input("srsi D 매수 제한 (예: 0.3): "))
            sell_time = int(input("매도감시횟수 (예: 25): "))
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
            df_5 = pyupbit.get_ohlcv(t, interval=min5, count=6)
            if df_5 is None:
                print(f"[filter_tickers] 데이터를 가져올 수 없습니다. {t}")
                send_discord_message(f"[filter_tickers] 데이터를 가져올 수 없습니다: {t}")
                continue  # 다음 티커로 넘어감
            time.sleep(second)
            df_close_5 = df_5['close'].values

            # df_15 = pyupbit.get_ohlcv(t, interval=min15, count=6)
            # if df_15 is None:
            #     print(f"[filter_tickers|df15] 데이터를 가져올 수 없습니다. {t}")
            #     send_discord_message(f"[filter_tickers|df15] 데이터를 가져올 수 없습니다: {t}")
            #     continue  # 다음 티커로 넘어감
            # time.sleep(second)
            # df_close_15 = df_15['close'].values

            bands_df = get_bollinger_bands(t, interval = min5)
            upper_band = bands_df['Upper_Band'].values
            lower_band = bands_df['Lower_Band'].values
            band_diff = (upper_band - lower_band) / lower_band

            slopes = np.diff(lower_band)
            decreasing = all(abs(slopes[i]) > abs(slopes[i + 1]) for i in range(2, len(slopes) - 1))

            # bands_df_15 = get_bollinger_bands(t, interval = min15)
            # upper_band_15 = bands_df_15['Upper_Band'].values
            # lower_band_15 = bands_df_15['Lower_Band'].values
            # band_diff_15 = (upper_band_15 - lower_band_15) / lower_band_15

            is_increasing = band_diff[-1] > 0.2 #band_diff[len(band_diff) - 1] > 0.02 #for i in range(len(band_diff) - 1))
            count_below_lower_band = sum(1 for i in range(len(lower_band)) if df_close_5[i] < lower_band[i])            
            # count_below_lower_band_15 = sum(1 for i in range(len(lower_band_15)) if df_close_15[i] < lower_band_15[i] * 1.005)
            low_boliinger = count_below_lower_band >= 1

            stoch_Rsi = stoch_rsi(t, interval = min5)
            srsi_k = stoch_Rsi['%K'].values
            srsi_d = stoch_Rsi['%D'].values
            srsi_d_rising = srsi_d[2] < srsi_k[2] and srsi_value_s < srsi_d[2] < srsi_value_e

            cur_price = pyupbit.get_current_price(t)

            if is_increasing :
                # print(f'{t} [con1] BOL 최소폭')
                # test_time = datetime.now().strftime('%m/%d %H:%M:%S')
                # print(f'[{test_time}] {t} \n [test1: {is_increasing}] band_diff_15: {band_diff_15[-1]:,.3f} > band_diff_5: {band_diff[-1]:,.3f}  \n [test2: {low_boliinger}] BOL 하단 1회 이상: low_bol: {lower_band[-1]:,.1f} > df_close: {df_close_5[-1]:,.1f} / low_bol15: {lower_band_15[-1]:,.1f} > df_close15 * 1.005: {df_close_15[-1] * 1.005:,.1f} \n [test3: {srsi_d_rising}] {srsi_value_s} < srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} < {srsi_value_e}]')
                # print(f'[{test_time}] {t} \n lBand_15: {lower_band_15[-1]:,.4f} > df_close15: {df_close_15[3]:,.1f} \n lBand_5: {lower_band[-1]:,.4f} > df_close: {df_close_5[3]:,.1f}')
                if low_boliinger :
                    if decreasing :
                        if srsi_d_rising :
                            test_time = datetime.now().strftime('%m/%d %H:%M:%S')
                            print(f'{t} [con3] SRSI K-D 교차 | 현재가: {cur_price:,1f} / {srsi_value_s} < srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} < {srsi_value_e}')
                            send_discord_message(f'[{test_time}] {t} [con3] SRSI K-D 교차 | 현재가: {cur_price:,1f} / {srsi_value_s} < srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} < {srsi_value_e}')
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

                df_240min = pyupbit.get_ohlcv(ticker, interval="minute240", count=2)
                time.sleep(second)
                day_240min_0 = df_240min['open'].iloc[0]
                day_240min_1 = df_240min['open'].iloc[1]
                
                cur_price = pyupbit.get_current_price(ticker)

                if cur_price < day_240min_0 * 1.05:
                    if cur_price < day_240min_1 * 1.05:
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
    interest = 0  # 초기 수익률

    for ticker in filtered_list:   # 조회할 코인 필터링
        df = pyupbit.get_ohlcv(ticker, interval=min5, count=5)
        time.sleep(second)
        if df is None or df.empty:
            continue
            
        df['ror'] = np.where(df['high'] > df['open'], df['close'] / df['open'], 1)  # 수익률 계산 : 시가보다 고가가 높으면 거래성사, 수익률(종가/시가) 계산
        df['hpr'] = df['ror'].cumprod()  # 누적 수익률 계산

        if interest < df['hpr'].iloc[-1]:  # 현재 수익률이 이전보다 높으면 업데이트
            bestC = ticker
            interest = df['hpr'].iloc[-1]

    return bestC  # 최고의 코인, 수익률, K 반환

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
    srsi_buy = srsi_value_s < srsi_d[2] < srsi_value_e and srsi_d[2] < srsi_k[2]

    if krw >= min_krw :
        while attempt < max_retries:
            print(f"[가격 확인 중]: {ticker} srsi_buy: {srsi_buy} / 현재가: {cur_price:,.2f} / 시도: {attempt} - 최대: {max_retries}")
            
            if srsi_buy :
                buy_attempts = 3
                for i in range(buy_attempts):
                    try:
                        buy_order = upbit.buy_market_order(ticker, buy_size)
                        send_discord_message(f"매수 성공: {ticker} / 현재가 :{cur_price:,.2f}")
                        return buy_order

                    except (KeyError, ValueError) as e:
                        print(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                        send_discord_message(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                        time.sleep(5 * (i + 1)) 

                return "Buy order failed", None
            else:
                attempt += 1  # 시도 횟수 증가
                time.sleep(2)

        print(f"[매수 실패]: {ticker} / 현재가: {cur_price:,.2f} / {srsi_value_s} < srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} < {srsi_value_e}")
        send_discord_message(f"[매수 실패]: {ticker} / 현재가: {cur_price:,.2f} / {srsi_value_s} < srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} < {srsi_value_e}")
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
    
    upper_price = (upper_boliinger and srsi_d[2] >= 0.85) or (srsi_d[2] >= 0.95) or (srsi_d[2] >= 0.75 and srsi_d[2] > srsi_k[2])
    middle_price = srsi_d[2] > srsi_k[2]
    cut_price = srsi_d[2] > srsi_k[2] or srsi_d[2] >= 0.95

    max_attempts = sell_time
    attempts = 0

    cut_time = datetime.now()
    cut_start = cut_time.replace(hour=8, minute=55, second=00, microsecond=0)
    cut_end = cut_time.replace(hour=9, minute=1, second=55, microsecond=0)

    if cut_start <= cut_time <= cut_end:      # 매도 제한시간이면
        if cut_price :
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            print(f"[장시작전매도]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
            send_discord_message(f"[장시작전매도]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
        else:
            time.sleep(1)
            return None  

    else:
        if profit_rate >= min_rate:
            while attempts < max_attempts:       
                print(f"[{ticker}] / [매도시도 {attempts + 1} / {max_attempts}] / 수익률: {profit_rate:.2f}% / upper_price : {upper_price}")

                if profit_rate >= max_rate or upper_price :
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    print(f"[!!목표가 달성!!]: [{ticker}] / 수익률: {profit_rate:.2f}%  / 현재가: {cur_price:,.1f} upper_price: {upper_price} / 0.85 < srsi_d {srsi_d[2]:,.2f}")
                    send_discord_message(f"[!!목표가 달성!!]: [{ticker}] / 수익률: {profit_rate:.2f}%  / 현재가: {cur_price:,.1f} upper_price: {upper_price} /  0.8 < srsi_d {srsi_d[2]:,.2f}")
                    return sell_order

                else:
                    time.sleep(second)
                attempts += 1  # 조회 횟수 증가
                
            if middle_price:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                print(f"[m_price 도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
                send_discord_message(f"[m_price 도달]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
                return sell_order   
            else:
                middle_price_time = datetime.now().strftime('%m/%d %H:%M:%S')
                print(f"[m_price 미도달]: [{middle_price_time}][{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f}")
                return None
        else:
            if profit_rate < cut_rate:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                print(f"[손절_CutRate]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
                send_discord_message(f"[손절_CutRate]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} / srsi_d: {srsi_d[2]:,.2f} > srsi_k: {srsi_k[2]:,.2f}")
            else:
                return None  

def send_profit_report():
    while True:
        try:
            now = datetime.now()  # 현재 시간을 루프 시작 시마다 업데이트 (try 루프안에 있어야 실시간 업데이트 주의)
            next_hour = (now + timedelta(hours = 1)).replace(minute = 0, second = 0, microsecond = 0)   # 다음 정시 시간을 계산 (현재 시간의 분, 초를 0으로 만들어 정시로 맞춤)
            time_until_next_hour = (next_hour - now).total_seconds()
            time.sleep(time_until_next_hour)    # 다음 정시까지 기다림

            balances = upbit.get_balances()     
            report_message = "현재 수익률 보고서:\n"
            
            for b in balances:
                if b['currency'] in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:  # 제외할 코인 리스트
                    continue
                
                ticker = f"KRW-{b['currency']}"
                buyed_amount = float(b['balance'])
                
                if buyed_amount > 0:
                    avg_buy_price = float(b['avg_buy_price'])
                    cur_price = pyupbit.get_current_price(ticker)
                    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0

                    stoch_Rsi = stoch_rsi(ticker, interval = min5)
                    srsi_k = stoch_Rsi['%K'].values
                    srsi_d = stoch_Rsi['%D'].values

                    stoch_Rsi_15 = stoch_rsi(ticker, interval = min15)
                    srsi_k15 = stoch_Rsi_15['%K'].values
                    srsi_d15 = stoch_Rsi_15['%D'].values

                    report_message += f"[{b['currency']}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.2f} \n srsi_d: {srsi_d[2]:,.2f} < srsi_k: {srsi_k[2]:,.2f} \n srsi_d15: {srsi_d15[2]:,.2f} < srsi_k15: {srsi_k15[2]:,.2f} \n"

            send_discord_message(report_message)

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