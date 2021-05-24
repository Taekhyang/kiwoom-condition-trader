import sys
import configparser
import threading
import queue
import re
import time

from enum import Enum
from PyQt5.QAxContainer import QAxWidget
from PyQt5 import QtWidgets
from PyQt5 import QtCore
from StockApis.kiwoom import KiwoomAPIModule
from KiwoomConditionTrader.database_connection import StockDatabase
from Util.debugger import *

cfg = configparser.ConfigParser()
cfg.read('Settings.ini')

CONDITION_LIST = [x.strip() for x in cfg['조건식이름']['목록'].split(',')]
ACCOUNT_NUM = cfg['계좌번호']['번호']
BUY_PRICE = float(cfg['매매금액']['금액'])
PROFIT_LIMIT = float(cfg['수익상한']['비율'])
LOSS_LIMIT = -(float(cfg['손실하한']['비율']))

if LOSS_LIMIT > 0:
    debugger.exception('손실하한 비율은 음수가 될 수 없습니다')
    raise Exception('손실하한 비율은 음수가 될 수 없습니다')

# 구매 시 시장가 변수
MARKET_PRICE = '03'


class Commands(Enum):
    SELL = 'sell'
    BUY = 'buy'
    APPLY_CONDITION = 'apply_condition'
    GET_CURRENT_PRICE = 'get_current_price'
    GET_REAL_CURRENT_PRICE = 'get_real_current_price'
    GET_CONDITIONS = 'get_conditions'
    GET_ORDER_HISTORY = 'get_order_history'
    REGISTER_CONDITION = 'register_condition'
    REGISTER_REAL_CURRENT_PRICE = 'register_real_current_price'
    CANCEL_SELL_STOCK = 'cancel_sell_stock'


class KiwoomConditionTrader(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.command_q = queue.Queue()
        self.database = StockDatabase()

        self.kiwoom_communicate_thread = KiwoomCommunicateThread(self.command_q, debugger)

        self.run_in_main()
        self.register_conditions()

    def run_in_main(self):
        self.kiwoom_communicate_thread.start()

        self.kiwoom_catch_condition_order = KiwoomCatchConditionOrder(self.command_q, self.database, debugger)
        self.kiwoom_catch_condition_order.start()

        self.kiwoom_check_real_current_price = KiwoomCheckRealCurrentPrice(self.command_q, self.database, debugger)
        self.kiwoom_check_real_current_price.start()

    def register_conditions(self):
        register_condition_callback_queue = queue.Queue()
        data = dict(command=Commands.REGISTER_CONDITION,
                    condition_list=CONDITION_LIST)
        self.command_q.put((register_condition_callback_queue, data))


class KiwoomCommunicateThread(QtCore.QThread):
    def __init__(self, command_q, debugger):
        super(KiwoomCommunicateThread, self).__init__()
        self.command_q = command_q
        self.debugger = debugger

        self.kiwoom = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.kiwoom.dynamicCall("CommConnect()")
        self.kiwoom_api = KiwoomAPIModule(self.kiwoom)
        self.connections()

        self.stopped = threading.Event()

    def connections(self):
        self.kiwoom.OnReceiveTrData.connect(self.kiwoom_api.receive_tx_data)
        self.kiwoom.OnReceiveChejanData.connect(self.kiwoom_api.receive_chejan_data)
        self.kiwoom.OnEventConnect.connect(self.kiwoom_api.connect_status_receiver)

        self.event_thread = QtCore.QThread()
        self.event_thread.start()

        self.kiwoom_api.moveToThread(self.event_thread)

        self.kiwoom.OnReceiveRealData.connect(self.kiwoom_api.receive_real_tx_data)
        self.kiwoom.OnReceiveConditionVer.connect(self.kiwoom_api.receive_condition_ver)
        self.kiwoom.OnReceiveRealCondition.connect(self.kiwoom_api.receive_real_condition)

    def register_conditions(self, condition_list):
        self.kiwoom_api.register_condition_list(condition_list)
        self.kiwoom_api.apply_conditions()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.kiwoom_api.is_connected:
            time.sleep(0.1)

        while not self.stopped.is_set():
            try:
                try:
                    callback_queue, data = self.command_q.get(True, 30)
                except:
                    continue
                ret = str()
                if data['command'] == Commands.REGISTER_CONDITION:
                    self.register_conditions(data['condition_list'])

                elif data['command'] == Commands.REGISTER_REAL_CURRENT_PRICE:
                    self.kiwoom_api.registry_real_current_price_data(data['stock_code_list'])

                elif data['command'] == Commands.GET_CONDITIONS:
                    ret = self.kiwoom_api.get_conditions()

                elif data['command'] == Commands.GET_CURRENT_PRICE:
                    ret = self.kiwoom_api.get_current_price(data['stock_code'])

                elif data['command'] == Commands.GET_REAL_CURRENT_PRICE:
                    ret = self.kiwoom_api.get_current_price_set(data['stock_code'])

                elif data['command'] == Commands.GET_ORDER_HISTORY:
                    ret = self.kiwoom_api.get_order_history(data['order_number'])

                elif data['command'] == Commands.BUY:
                    ret = self.kiwoom_api.buy_stock(data['account_num'],
                                                    data['stock_code'],
                                                    data['qty'],
                                                    trade_type=MARKET_PRICE
                                                    )

                elif data['command'] == Commands.SELL:
                    ret = self.kiwoom_api.sell_stock(data['account_num'],
                                                     data['stock_code'],
                                                     data['qty'],
                                                     trade_type=MARKET_PRICE
                                                     )
                callback_queue.put(ret)
            except Exception as e:
                self.debugger.exception(e)
                callback_queue.put('')


class KiwoomCheckRealCurrentPrice(threading.Thread):
    """
    1. DB에 있는 매수 체결된 종목들 실시간 현재가 이벤트 받기 등록
    2. 실시간 현재가와 매수체결가격 비교하면서 수익상한과 수익하한 범위 밖이면 매도 및 DB에서 해당 종목코드 삭제
    """

    def __init__(self, command_q, database, debugger):
        super().__init__()
        self.command_q = command_q
        self.database = database
        self.debugger = debugger

        self.stopped = threading.Event()

        self.stock_real_price_register_history = dict()
        self.pending_sell_order_number_list = list()

    def stop(self):
        self.stopped.set()

    def is_sell_timing(self, stock_code, current_price, price):
        try:
            earning_rate = ((current_price / price) - 1) * 100
        except ZeroDivisionError:
            self.debugger.debug('{} : price is zero'.format(stock_code))
            return False

        if LOSS_LIMIT < earning_rate < PROFIT_LIMIT:
            return False
        elif earning_rate < LOSS_LIMIT:
            self.debugger.info('{} : 손익율 {}%, 손실하한 미만으로 매도합니다'.format(stock_code, earning_rate))
        elif earning_rate > PROFIT_LIMIT:
            self.debugger.info('{} : 손익율 {}%, 수익상한 초과로 매도합니다'.format(stock_code, earning_rate))
        return True

    def run(self):
        while not self.stopped.wait(1):
            # db에 매수 체결된 종목들 실시간 현재가 이벤트 받기 등록
            # db에서 이미 실시간 현재가 이벤트 등록이 되어있으면 pass 함
            all_stock_order_history = self.database.get_all_stock_order_history()

            # loop 마다 DB 주문기록 업데이트
            stock_order_history = dict()
            for order_history in all_stock_order_history:
                buy_order_number, stock_code, amount, price, sell_order_number = order_history
                stock_order_history.setdefault(buy_order_number,
                                               dict(
                                                   order_number=buy_order_number,
                                                   stock_code=stock_code,
                                                   amount=amount,
                                                   price=price,
                                                   sell_order_number=sell_order_number)
                                               )

            # DB 종목별 실시간 real 이벤트 등록 기록
            for order_history in all_stock_order_history:
                _, stock_code, _, _, _ = order_history
                self.stock_real_price_register_history.setdefault(stock_code, dict(registered=False))

            # 실시간 현재가 등록할 종목코드 찾기
            if self.stock_real_price_register_history:
                stock_codes_to_register = list()

                for buy_order_number in stock_order_history.keys():
                    stock_code = stock_order_history[buy_order_number]['stock_code']

                    # 종목 하나라도 register 되지 않았다면 모두 등록하고 registered True로 바꾸기
                    if not self.stock_real_price_register_history[stock_code]['registered']:
                        for stock_code in self.stock_real_price_register_history:
                            stock_codes_to_register.append(stock_code)
                            self.stock_real_price_register_history[stock_code]['registered'] = True
                        break

                if stock_codes_to_register:
                    register_real_current_price_callback_queue = queue.Queue()
                    data = dict(command=Commands.REGISTER_REAL_CURRENT_PRICE,
                                stock_code_list=stock_codes_to_register
                                )
                    self.debugger.info('{} : 해당종목을 실시간 가격 이벤트에 등록합니다'.format(stock_codes_to_register))
                    self.command_q.put((register_real_current_price_callback_queue, data))

            # DB에서 종목별 매수가와 실시간으로 받아온 현재가 비교로직
            for buy_order_number in stock_order_history.keys():
                stock_code = stock_order_history[buy_order_number]['stock_code']

                get_real_current_price_callback_queue = queue.Queue()
                data = dict(command=Commands.GET_REAL_CURRENT_PRICE,
                            stock_code=stock_code
                            )
                self.command_q.put((get_real_current_price_callback_queue, data))
                try:
                    current_price = get_real_current_price_callback_queue.get(timeout=20)
                except:
                    current_price = None

                if not current_price:
                    self.debugger.debug('{} : failed to get real current price'.format(stock_code))
                    continue

                # 현재가와 매수가격 비교 뒤 수익률이 LOSS_LIMIT 과 PROFIT_LIMIT 영역 밖이면 매도
                # 매도성공시 리턴값으로 주문번호(order_number) 받음
                buy_price = stock_order_history[buy_order_number]['price']

                # 매도주문체결 완료되지 않은 종목 손익률 비교 하지 않음
                if stock_order_history[buy_order_number]['sell_order_number']:
                    continue

                # 손익률 비교
                if self.is_sell_timing(stock_code, current_price, buy_price):
                    order_amount = stock_order_history[buy_order_number]['amount']

                    sell_callback_queue = queue.Queue()
                    data = dict(command=Commands.SELL,
                                account_num=ACCOUNT_NUM,
                                stock_code=stock_code,
                                qty=order_amount
                                )
                    self.debugger.info('{} : 해당 종목을 {} 개만큼 매도합니다'.format(stock_code, order_amount))

                    self.command_q.put((sell_callback_queue, data))
                    try:
                        sell_order_number = sell_callback_queue.get(timeout=20)
                    except:
                        sell_order_number = None

                    # 매도주문번호 리턴값이 에러코드면 주문 실패
                    if re.compile('[^0-9]').match(sell_order_number) or not sell_order_number:
                        self.debugger.debug('{} : sell order failed, error code {}'.format(stock_code, sell_order_number))
                        continue

                    # 매도 후 주문번호를 정상적으로 리턴했으면 매도주문에 성공, db에서 해당종목 삭제
                    self.debugger.info('{} : 주문번호 - {}, 매도주문에 성공했습니다'.format(stock_code, sell_order_number))

                    # 매도주문번호 매수주문번호 row 에 DB에 저장, 기억하고 있다가 나중에 매도체결 완료되면 매도주문번호로 DB 에서 삭제
                    try:
                        self.database.add_sell_order_history(buy_order_number, sell_order_number)
                        self.debugger.info('매도주문번호 - {}, DB에 저장하였습니다'.format(sell_order_number))

                        self.pending_sell_order_number_list.append(sell_order_number)
                    except Exception as e:
                        self.debugger.exception('매도주문번호 저장 실패, error - {}'.format(e))

            # 주문체결번호 리스트 돌면서 전량 매도된 주문 DB에서 삭제
            for sell_order_number in self.pending_sell_order_number_list:
                time.sleep(1)
                get_order_history_callback_queue = queue.Queue()
                data = dict(command=Commands.GET_ORDER_HISTORY,
                            order_number=sell_order_number,
                            )
                self.debugger.debug('order number {} : started getting order history'.format(data['order_number']))
                self.command_q.put((get_order_history_callback_queue, data))

                try:
                    order_history = get_order_history_callback_queue.get(timeout=20)
                except:
                    order_history = None

                if not order_history:
                    continue

                stock_code = order_history['stock_code']
                order_amount = order_history['amount']
                filled = order_history['filled']
                filled_price = order_history['filled_price']

                # 주문량과 체결량이 같을 때 DB에서 삭제
                if order_amount == filled:
                    try:
                        self.database.remove_stock_order_history(sell_order_number)
                        self.debugger.info(
                            '{} : 주문번호 - {} DB 삭제 성공, {} 에 {} 개만큼 매도했습니다'.format(stock_code, sell_order_number,
                                                                                    filled_price, filled))
                    except Exception as e:
                        self.debugger.exception(
                            '{} : 주문번호 - {} DB 에서 삭제하는데 실패했습니다, error - {}'.format(stock_code, sell_order_number, e))

                    self.pending_sell_order_number_list.remove(sell_order_number)


class KiwoomCatchConditionOrder(threading.Thread):
    def __init__(self, command_q, database, debugger):
        super().__init__()
        self.command_q = command_q
        self.database = database
        self.debugger = debugger

        self.stopped = threading.Event()

        self.meet_real_conditions_history = list()
        self.pending_buy_order_number_list = list()

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.wait(1):
            # 콜백 큐 만들고 command_q에 추가, 조건식 이벤트로 나온 종목들이 있는지 수시로 체크
            get_condition_callback_queue = queue.Queue()
            data = dict(command=Commands.GET_CONDITIONS)

            self.command_q.put((get_condition_callback_queue, data))
            try:
                condition_stock_codes = get_condition_callback_queue.get(timeout=20)
            except:
                condition_stock_codes = list()

            # 조건식 이벤트 받았다고 가정하는 테스트 코드 -->
            # condition_stock_codes = ['005935']

            # 매수기록과 새로 받아온 조건식 매치 종목들 비교
            # 조건식 매치 종목이 매수기록에 없으면 이탈했다는 뜻, 해당 종목 매수기록에서 삭제
            for stock_code in self.meet_real_conditions_history:
                if stock_code not in condition_stock_codes:
                    self.meet_real_conditions_history.remove(stock_code)
                    self.debugger.info('{} : 해당 종목이 조건식에서 이탈했습니다'.format(stock_code))

            # 조건식 이벤트 발생시 나온 종목들이 있는경우, 해당 종목들 시장가로 차례로 주문
            if condition_stock_codes:
                for stock_code in condition_stock_codes:
                    # 매수기록에 조건식 매치 종목이 있으면 이미 매수 했다는 뜻
                    if stock_code in self.meet_real_conditions_history:
                        continue
                    self.debugger.info('조건식에 맞는 종목을 캐치했습니다 - {}'.format(stock_code))

                    # 몇 주 주문할지 계산하기 위해 현재가 가져오기
                    get_current_price_callback_queue = queue.Queue()
                    data = dict(command=Commands.GET_CURRENT_PRICE,
                                stock_code=stock_code)

                    self.command_q.put((get_current_price_callback_queue, data))
                    try:
                        current_price = get_current_price_callback_queue.get(timeout=20)
                    except:
                        current_price = None

                    # 현재가 가져오는데 실패하면 다음 iteration 에 다시시도
                    if not current_price:
                        self.debugger.debug('{} : failed to get current price'.format(stock_code))
                        continue

                    # 매수금액(BUY_PRICE)을 1주당 현재가로 나눈 가격만큼 매수 주문
                    order_amount = int(BUY_PRICE // current_price)
                    self.debugger.info('{} : 주문 수량 - {}'.format(stock_code, order_amount))

                    if order_amount == 0:
                        self.debugger.info('{} : 주가가 매매금액을 초과하여 주문을 체결하지 않습니다'.format(stock_code))
                        self.meet_real_conditions_history.append(stock_code)
                        continue

                    buy_callback_queue = queue.Queue()
                    data = dict(command=Commands.BUY,
                                account_num=ACCOUNT_NUM,
                                stock_code=stock_code,
                                qty=order_amount
                                )
                    self.debugger.info('{} : 해당 종목을 {} 개만큼 매수합니다'.format(stock_code, order_amount))

                    self.command_q.put((buy_callback_queue, data))
                    try:
                        order_number = buy_callback_queue.get(timeout=20)
                    except:
                        order_number = None

                    # 매수 후 주문번호 리턴값이 에러코드면 주문 실패, 다음 iteration 에 시도
                    # 다음 종목코드로 넘어감
                    if re.compile('[^0-9]').match(order_number) or not order_number:
                        self.debugger.info('{} : 매수 주문 실패 {}'.format(stock_code, order_number))
                        continue

                    self.debugger.info('{} : 매수 주문 성공, 주문번호 - {}'.format(stock_code, order_number))
                    self.pending_buy_order_number_list.append(order_number)

                    # 매수 후 해당 종목 _meet_real_condition_history 에 기록해서 이탈 전 재구매 방지
                    self.meet_real_conditions_history.append(stock_code)

            # 주문체결번호 리스트 돌면서 체결된 주문 DB에 저장
            for order_number in self.pending_buy_order_number_list:
                time.sleep(2)
                get_order_history_callback_queue = queue.Queue()
                data = dict(command=Commands.GET_ORDER_HISTORY,
                            order_number=order_number,
                            )
                self.debugger.debug('order number {} : started getting order history'.format(order_number))

                self.command_q.put((get_order_history_callback_queue, data))
                try:
                    order_history = get_order_history_callback_queue.get(timeout=20)
                except:
                    continue

                stock_code = order_history['stock_code']
                order_amount = order_history['amount']
                filled = order_history['filled']
                filled_price = order_history['filled_price']

                # 주문량과 체결량이 같을 때 DB 저장
                if order_amount == filled:
                    try:
                        self.database.add_stock_order_history(order_number, stock_code, order_amount, filled_price)
                        self.debugger.info(
                            '{} : 주문번호 - {} DB 저장 성공, 해당 종목 {} 주를 {} 에 매수했습니다'.format(stock_code, order_number,
                                                                                        order_amount, filled_price))

                        self.pending_buy_order_number_list.remove(order_number)
                    except Exception as e:
                        self.debugger.exception(
                            '{} : 주문번호 - {} 해당 종목을 DB에 저장하는데 실패했습니다, error - {}'.format(stock_code, order_number, e))


if __name__ == '__main__':
    try:
        app = QtWidgets.QApplication([])
        command_q = queue.Queue()
        stock_database = StockDatabase()
        KiwoomConditionTrader()
        app.exec_()
    except:
        debugger.exception("FATAL")
        debugger.info('개발자에게 모든 로그를 보내주세요!')
    finally:
        os.system("PAUSE")
        debugger.debug("DONE")
