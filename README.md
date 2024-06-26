## Kiwoom Condition Trader

*증권사 키움 API 를 사용하여 주식 자동 매매를 구현한 프로젝트입니다.*

*키움* *HTS* *조건식에 등록된 조건을 실시간으로 캐치하여 해당 조건에 맞는 종목을 매수한 뒤*

*유저가 설정해 둔 상한/하한 손익률 초과시 자동으로 매매하는 프로그램 입니다.*

*Python 으로 구현했으며, 키움 모의투자 HTS 를 이용하여 프로그램을 직접 테스트했습니다.*

**기술스택**

- Python 3,  SQLite

**세부내용**

- 조건식을 캐치하면 해당 종목을 매수하는 Thread, 실시간 현재가를 체크하여 상한/하한 손익률 초과 시 매도하는 Thread, 각각의 매수/매도 Thread 에서 받은 요청을 처리하는 Communicate Thread 로 구분
- 매수/매도 Thread 에서 command queue 에 callback queue 와 data 를 담아 넘기면, Communicate Thread 에서 data 값을 받아 요청을 처리한 후 다시 callback queue 에 값을 담아 리턴하는 로직 구현
- SQLite 를 사용하여 유저의 매매 기록 관리
- Python 의 Rotating Filehandler 를 활용한 Debugger 를 구현하여 시간 별 디버깅 관리
- 키움 API 요청 모듈화 작업


## Kiwoom Condition Trader

*This is a project that uses the Kiwoom(Stock brokage firm) API to implement automatic stock trading.*

*It is a program that catches the conditions registered in Kiwoom HTS conditional formula in real time, buys stocks that meet the conditions, and automatically sells them when the upper/lower profit or loss rate set by the user is exceeded.*

*The project was implemented using Python 3 and tested the program using Kiwoom Mock Investment HTS.*

**Tech Stack**

- Python 3,  SQLite

**Details**

- We implemented multi-threading as follows: Thread to buy the stock when caught conditional, Thread to check the real-time present price and sell when the upper/lower profit or loss ratio is exceeded, and "Communicate Thread" to handle requests received by each buy/sell Thread.
- If the buy/sell Thread puts callback queue and data in the command queue, the "Communicate Thread" takes the data value, processes the request, and then returns the value in the callback queue.
- Used SQLite to manage sales history for users.
- Clear chronological log management with Debugger implemented with Python's Rotating Filehandler.
- Modularized Kiwoom API requests.

