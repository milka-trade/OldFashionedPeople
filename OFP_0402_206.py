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

def send_discord_message(msg):
    """discord 메시지 전송"""
    try:
        message ={"content":msg}
        requests.post(DISCORD_WEBHOOK_URL, data=message)
    except Exception as e:
        print(f"디스코드 메시지 전송 실패 : {e}")
        time.sleep(5) 

count_200 = 200

min5 = "minute5"

rsi_buy_s = 25
rsi_buy_e = 40

band_diff_margin = 0.015
average_band_diff_rate = 1.05

UpRsiRate = 65

rsi_sell_s = 45
rsi_sell_e = 65

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 0.15): "))
            max_rate = float(input("최대 수익률 (예: 1.0): "))
            sell_time = int(input("매도감시횟수 (예: 200): "))
            break  # 모든 입력이 성공적으로 완료되면 루프 종료
        except ValueError:
            print("잘못된 입력입니다. 다시 시도하세요.")

    return min_rate, max_rate, sell_time

# 함수 호출 및 결과 저장
min_rate, max_rate, sell_time = get_user_input()

second = 1.0
min_krw = 50_000
cut_rate = -3.0

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
    
def stoch_rsiS(ticker, interval = min5, window=14):
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count_200)
    time.sleep(second)
     
    rsi = ta.momentum.RSIIndicator(df['close'], window=7).rsi()
    min_rsi = rsi.rolling(window = window).min()
    max_rsi = rsi.rolling(window = window).max()
        
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

def get_rsi(ticker, period, interval=min5):
    df_rsi = pyupbit.get_ohlcv(ticker, interval=interval, count=200) 
    if df_rsi is None or df_rsi.empty:
        return None  # 데이터가 없으면 None 반환

    # TA 라이브러리를 사용하여 RSI 계산
    rsi = ta.momentum.RSIIndicator(df_rsi['close'], window=period).rsi()

    return rsi.tail(3) if not rsi.empty else None 

def get_bollinger_bands(ticker, interval = min5, window=20, std_dev=2.5):
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

    return bands_df.tail(4)

def filtered_tickers(tickers):
    """특정 조건에 맞는 티커 필터링"""
    filtered_tickers = []
    
    for t in tickers:
        try:
            df = pyupbit.get_ohlcv(t, interval=min5, count=4)
            if df is None:
                print(f"[filter_tickers] 데이터를 가져올 수 없습니다. {t}")
                send_discord_message(f"[filter_tickers] 데이터를 가져올 수 없습니다: {t}")
                continue  # 다음 티커로 넘어감
            time.sleep(second)
            df_close = df['close'].values
            
            bands_df = get_bollinger_bands(t, interval = min5, window=20, std_dev=2.5)
            upper_band = bands_df['Upper_Band'].values
            lower_band = bands_df['Lower_Band'].values
            band_diff = (upper_band - lower_band) / lower_band

            average_band_diff = np.mean(band_diff)

            is_increasing_5 = band_diff[-1] > max(band_diff_margin, average_band_diff * average_band_diff_rate)
            
            last_ema5 = get_ema(t, interval = min5).iloc[-1]

            count_below_lower_band = sum(1 for i in range(len(lower_band)) if df_close[i] < min(lower_band[i]  * 1.005, last_ema5))
            
            low_boliinger = count_below_lower_band >= 1 
            
            slopes = np.diff(lower_band)
            slopeRate = 0.75
            low_band_slope_decreasing = abs(slopes[-2]) * slopeRate > abs(slopes[-1])
                
            ta_rsi = get_rsi(t, 14, interval = min5)
            rsi = ta_rsi.values
            rsi_rising = rsi[-2] < rsi[-1] and rsi_buy_s < rsi[-1] < rsi_buy_e
        
            filteringTime = datetime.now().strftime('%m/%d %H:%M:%S')  # 시작시간 기록
            filtering_message = f"<<[{filteringTime}] {t}>>\n"
            filtering_message += f"[cond1: {is_increasing_5}] band_diff: {band_diff[-1]:,.4f} > average*{average_band_diff_rate}: {average_band_diff*average_band_diff_rate:,.4f} / band_diff_margin: {band_diff_margin} \n"
            # filtering_message += f"[cond1: {is_increasing_5}] average_band_diff: {average_band_diff[-1]} > {average_band_diff[-4]} > {average_band_diff[-5]} \n"
            # filtering_message += f"[cond2: {low_boliinger15}] LB15: {lower_band15[-1]:,.2f} or ema15: {last_ema15:,.2f} > df15_close: {df15_close[-1]:,.2f} \n"
            filtering_message += f"[cond2: {low_band_slope_decreasing}] LBSlopes: {slopes[-2] * slopeRate:,.3f} >> {slopes[-1]:,.3f} \n"
            filtering_message += f"[cond3: {low_boliinger}] LB: {lower_band[-1]:,.2f} or ema5: {last_ema5:,.2f} > df_close: {df_close[-1]:,.2f} \n"
            # filtering_message += f"[cond6: {red_candle}] df_open: {df_open[-1]:,.2f} < df_close: {df_close[-1]:,.2f} \n"
            filtering_message += f"[cond4: {rsi_rising}] {rsi_buy_s} > rsi: {rsi[-3]:,.2f} >> {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} << > {rsi_buy_e} \n"

            # print(filtering_message)
            if is_increasing_5 :
                print(filtering_message)
                # send_discord_message(filtering_message)
                                    
                # if low_boliinger15 :
                #     print(filtering_message)
                #     send_discord_message(filtering_message)
                            
                if low_boliinger :
                    # print(filtering_message)

                    if low_band_slope_decreasing :
                        # print(filtering_message)
                        # send_discord_message(filtering_message)

                        if rsi_rising:
                            # print(filtering_message)
                            send_discord_message(filtering_message)
                            filtered_tickers.append(t)

        except (KeyError, ValueError) as e:
            send_discord_message(f"filtered_tickers/Error processing ticker {t}: {e}")
            time.sleep(5) 

    return filtered_tickers

def get_best_ticker():
    selected_tickers = ["KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-HBAR", "KRW-XLM", "KRW-DOGE"]  #"KRW-BTC", 
    # excluded_tickers = ["KRW-QI", "KRW-ONX", "KRW-ETHF", "KRW-ETHW", "KRW-PURSE", "KRW-USDT", "KRW-BERA", "KRW-VTHO", "KRW-SBD", "KRW-JTO", "KRW-SCR", "KRW-VIRTUAL", "KRW-SOLVE", "KRW-IOST", "KRW-HIFI", "KRW-WAL", "KRW-ORCA", "KRW-CRO", "KRW-LOOM", "KRW-ARKM", "KRW-KAITO", "KRW-COW", "KRW-TRUMP"]  # 제외할 코인 리스트
    balances = upbit.get_balances()
    held_coins = []

    for b in balances:
        if float(b['balance']) > 0:  # 보유량이 0보다 큰 경우
            ticker = f"KRW-{b['currency']}"  # 현재가 조회를 위한 티커 설정
            held_coins.append(ticker)  # "KRW-코인명" 형태로 추가
    
    try:
        # df_criteria = pyupbit.get_ohlcv('KRW-ADA', interval="day", count=1)
        # time.sleep(0.1)
        # krw_cri_day_value = df_criteria['value'].iloc[-1]  # KRW-SOL의 당일 거래량

        all_tickers = pyupbit.get_tickers(fiat="KRW")
        filtering_tickers = []

        for ticker in all_tickers:
            # if ticker not in excluded_tickers or ticker in selected_tickers :
            #     if ticker not in held_coins : 

            if ticker in selected_tickers and ticker not in held_coins:

                    df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
                    time.sleep(second)
                    df_open = df['open'].iloc[-1]
                    # df_close = df['close'].iloc[-1]
                    # df_value = df['value'].iloc[-1]

                    cur_price = pyupbit.get_current_price(ticker)

                    candle_cond = df_open * 0.98 < cur_price < df_open * 1.03
                    # value_cond = df_value >= krw_cri_day_value

                    if candle_cond :
                        # if value_cond :
                            filtering_tickers.append(ticker)
                                
    except (KeyError, ValueError) as e:
        send_discord_message(f"get_best_ticker/티커 조회 중 오류 발생: {e}")
        time.sleep(second) 
        return None

    filtered_list = filtered_tickers(filtering_tickers)
    # filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
    # print(filtered_list)
    # send_discord_message(f"{filtered_time} [{filtered_list}]")

    if len(filtered_list) > 0 :
        filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
        send_discord_message(f"{filtered_time} [{filtered_list}]")
    
    if len(filtered_list) == 1:
        return filtered_list[0]  # 티커가 1개인 경우 해당 티커 반환
    
    bestC = None  # 초기 최고 코인 초기화
    # low_srsi_d = float('inf')  # 가장 낮은 srsi 'D' 값 초기화
    low_rsi = float('inf')  # 가장 낮은 rsi 값 초기화

    for ticker in filtered_list:   # 조회할 코인 필터링
        
        ta_rsi = get_rsi(ticker, 14, interval = min5)
        rsi = ta_rsi.values
        current_rsi = rsi[-1]  # 가장 최근 rsi 값
            
        if current_rsi < low_rsi:  # 현재 'D' 값이 가장 낮으면 업데이트
            bestC = ticker
            low_rsi = current_rsi

        time.sleep(second)  # API 호출 간 대기
    return bestC   # 가장 낮은 rsi 값을 가진 코인 반환

def trade_buy(ticker):
    
    krw = get_balance("KRW")
    max_retries = 5
    # buy_size = min(trade_Quant, krw*0.9995)
    buy_size = krw*0.9995
    cur_price = pyupbit.get_current_price(ticker)    
    attempt = 0 

    ta_rsi = get_rsi(ticker, 14, interval = min5)
    rsi = ta_rsi.values
    
    rsi_rising = rsi[-2] < rsi[-1] and rsi_buy_s < rsi[-1] < rsi_buy_e
    
    last_ema = get_ema(ticker, interval = min5).iloc[-1]

    if krw >= min_krw :
        while attempt < max_retries:
            print(f"[가격 확인 중]: {ticker} rsi_rising: {rsi_rising} / 현재가: {cur_price:,.2f} / 시도: {attempt} - 최대: {max_retries}")
            
            if (rsi_rising and cur_price < last_ema) : #or (rsi_cross and cur_price < last_ema) :
                    buy_attempts = 3
                    for i in range(buy_attempts):
                        try:
                            buy_order = upbit.buy_market_order(ticker, buy_size)
                            buyedmsg = f"매수 성공: {ticker} / 현재가 :{cur_price:,.2f} \n"
                            buyedmsg += f"{rsi_rising} rsi_rising >> {rsi_buy_s} < rsi: {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} < {rsi_buy_e} \n"
                            print(buyedmsg)
                            send_discord_message(buyedmsg)
                            return buy_order

                        except (KeyError, ValueError) as e:
                            print(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                            send_discord_message(f"매수 주문 실행 중 오류 발생: {e}, 재시도 중...({i+1}/{buy_attempts})")
                            time.sleep(5 * (i + 1)) 

            return "Buy order failed", None
        else:
                attempt += 1  # 시도 횟수 증가
                time.sleep(2)
        
        buyFailmsg = f"[매수 실패]: {ticker} / 현재가: {cur_price:,.2f} \n"
        buyFailmsg +=f"{rsi_buy_s} < rsi: {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} < {rsi_buy_e} \n"
        
        print(buyFailmsg)
        send_discord_message(buyFailmsg)
        return "Price not in range after max attempts", None
            
def trade_sell(ticker):
    currency = ticker.split("-")[1]
    buyed_amount = get_balance(currency)
    
    avg_buy_price = upbit.get_avg_buy_price(currency)
    cur_price = pyupbit.get_current_price(ticker)
    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0  # 수익률 계산

    df = pyupbit.get_ohlcv(ticker, interval = min5, count = 4)
    time.sleep(second)
    df_close = df['close'].values

    bands_df = get_bollinger_bands(ticker, interval = min5, window=20, std_dev=2.5)
    up_Bol = bands_df['Upper_Band'].values
    count_upper_band = sum(1 for i in range(len(up_Bol)) if up_Bol[i] < df_close[i] )
    upper_boliinger = count_upper_band >= 1
    
    ta_rsi = get_rsi(ticker, 14, interval = min5)
    rsi = ta_rsi.values
    
    upper_price = rsi[-1] > UpRsiRate
    middle_price = (rsi_sell_s <= rsi[-1] <= rsi_sell_e) and rsi[-2] > rsi[-1]
    cut_price = middle_price or upper_price or upper_boliinger

    max_attempts = sell_time
    attempts = 0

    cut_time = datetime.now()
    cut_start = cut_time.replace(hour=8, minute=58, second=00, microsecond=0)
    cut_end = cut_time.replace(hour=8, minute=59, second=55, microsecond=0)

    if cut_start <= cut_time <= cut_end:      # 매도 제한시간이면
        if cut_price :
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            cutTimemsg = f"[장시작전매도]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} \n"
            cutTimemsg += f" {rsi_sell_s} < rsi: {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} < {rsi_sell_e}  \n"
            print(cutTimemsg)
            send_discord_message(cutTimemsg)
        else:
            time.sleep(1)
            return None  

    else:
        if profit_rate >= min_rate:
            while attempts < max_attempts:       
                print(f"[{ticker}] / [매도시도 {attempts + 1} / {max_attempts}] / 수익률: {profit_rate:.2f}% / upper_price : {upper_price}")

                if profit_rate >= max_rate or upper_boliinger or upper_price or middle_price:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    sellmsg = f"[!!익절!!]:[{ticker}] / 수익률: {profit_rate:.2f}%  / 현재가: {cur_price:,.1f} \n"
                    sellmsg += f"upper_Bol: {upper_boliinger} / {rsi_sell_s} < rsi: {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} < {rsi_sell_e} \n \n"

                    print(sellmsg)
                    send_discord_message(sellmsg)
                    return sell_order

                else:
                    time.sleep(second)
                attempts += 1  # 조회 횟수 증가
                
        else:
            if profit_rate < cut_rate:
                if cut_price:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    cut_message = f"[손절_CutRate_3%]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f} \n"
                    cut_message += f" {rsi_sell_s} < rsi: {rsi[-2]:,.2f} >> {rsi[-1]:,.2f} < {rsi_sell_e}  \n"
                    
                    print(cut_message)
                    send_discord_message(cut_message)            
            else:
                return None  

def send_profit_report():
    first_run = True  # 처음 실행 여부를 체크하는 변수

    while True:
        try:
            now = datetime.now()  # 현재 시간을 루프 시작 시마다 업데이트
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            time_until_next_hour = (next_hour - now).total_seconds()
            report_message = f" 현재 수익률 보고서:\n"
            balances = upbit.get_balances()

            if isinstance(balances, list):              # balances가 리스트인지 확인
                for b in balances:
                    if isinstance(b, dict) and 'currency' in b:                     # b가 딕셔너리인지 확인
                        if b['currency'] in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                            continue

                        ticker = b['currency']  # 티커를 currency로 설정
                        buyed_amount = get_balance(ticker)  # get_balance 함수 사용

                        if buyed_amount > 0:
                            avg_buy_price = float(b['avg_buy_price'])
                            cur_price = pyupbit.get_current_price(f"KRW-{ticker}")
                            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
                            
                            ta_rsi = get_rsi(f"KRW-{ticker}", 14, interval = min5)
                            rsi = ta_rsi.values

                            report_message += f"[{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.2f} / 보유량: {buyed_amount:.2f} / 평균 매수 가격: {avg_buy_price:.2f} \n"
                            report_message += f"rsi: {rsi[-2]:,.3f} >> {rsi[-1]:,.3f} \n"
                    
                        else:
                            report_message += "RSI 데이터가 충분하지 않습니다.\n"
                send_discord_message(report_message)

                if first_run:                   # 첫 실행 이후 대기
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
trade_msg = f'{trade_start} trading start \n'
trade_msg += f'매도: {min_rate}% ~ {max_rate}% / 시도: {sell_time}회 RsiBuy: {rsi_buy_s} ~ {rsi_buy_e} / RsiSell: {rsi_sell_s} ~ {rsi_sell_e} / 손절: {cut_rate}% \n'  #/ SrsiBuy: {srsi_value_s} ~ {srsi_value_e} 

print(trade_msg)
send_discord_message(trade_msg)

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