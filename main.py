import asyncio
import platform
import os

from sys import stdout
from loguru import logger

from web3 import AsyncWeb3
from datetime import datetime, timezone
from curl_cffi.requests import AsyncSession
from eth_account.messages import encode_defunct

from config import chipPieceContract, chipVendorMachineContract, USE_PROXY

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Web3GoMinter:
    def __init__(self, thread: int, private_key: str, proxy: str = None) -> None:
        self.thread = thread

        self.private_key = private_key
        self.address = AsyncWeb3().eth.account.from_key(private_key).address
        
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider('https://opbnb-mainnet-rpc.bnbchain.org', request_kwargs = {'proxy': proxy} if proxy else None))
        self.session = AsyncSession(proxy=proxy, impersonate="chrome")

    async def check_proxy(self):
        try:
            r = await self.session.get('https://api.ipify.org/?format=json', timeout = 5)
            await self.session.get('https://reiki.web3go.xyz', timeout = 5) #ssl ping bproxy
        except Exception:
            logger.error(f"Поток {self.thread} | Прокси недоступпен - {self.session.proxies['all']}")
            return False
        else:
            logger.success(f"Поток {self.thread} | Прокси доступен {r.json()['ip']}")
            return True

    async def login(self) -> None:
        r = await self.session.post('https://reiki.web3go.xyz/api/account/web3/web3_nonce', json = {"address":"0x"})
        ans = r.json()

        msg = f"web3go.xyz wants you to sign in with your Ethereum account:\n{self.address}\n\nSign in to the Web3Go Airdrop.\n\nURI: https://web3go.xyz\nVersion: 1\nChain ID: 204\nNonce: {ans['nonce']}\nIssued At: {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}"

        payload = {"address": self.address,
                   "nonce": ans['nonce'],
                   "challenge": '{"msg":"' + msg.replace('\n', '\\n') + '"}',
                   "signature": await self.sign_message(msg)}
        
        r = await self.session.post('https://reiki.web3go.xyz/api/account/web3/web3_challenge', json = payload)
        ans = r.json()
        
        self.session.headers['Authorization'] = f'Bearer {ans['extra']['token']}'
        logger.info(f"Поток {self.thread} | Начал работу | PrivateKey: {self.private_key}")
    
    async def get_offchain(self) -> tuple:
        r = await self.session.get("https://reiki.web3go.xyz/api/lottery/offchain")
        ans = r.json()
        return ans['pieceNum'], ans['chipNum']

    async def get_mint_info(self):
        r = await self.session.get('https://reiki.web3go.xyz/api/lottery/mint/info')
        return r.json()['mintedChip']
    
    async def mint_piece(self, piece):
        payload = {"addressThis":"0x2c085411ca401a84a9D98DEc415282FA239D53bB",
                    "numPieces":piece,
                    "chainId":204,
                    "type":"chipPiece"}

        r = await self.session.post("https://reiki.web3go.xyz/api/lottery/claim", json = payload)
        ans = r.json()

        if ans['result']:
            contract_address = '0x2c085411ca401a84a9D98DEc415282FA239D53bB'
            args = (contract_address, self.address, 0, piece, 204, self.w3.to_int(hexstr=ans['nonce']), self.w3.to_bytes(hexstr=ans['signature']))

            data = await self.w3.eth.contract(contract_address, abi=chipPieceContract).functions.claim(*args).build_transaction({
                'from': self.address,
                'gasPrice': self.w3.to_wei('0.00001', 'gwei'), 
                'nonce': await self.w3.eth.get_transaction_count(self.address),
                'chainId': 204
                })
            data['gas'] = int((await self.w3.eth.estimate_gas(data))*1.01)
            hash = await self.send_txn(data)

            while True:
                r = await self.session.post("https://reiki.web3go.xyz/api/lottery/claimSuccess", json = {"eventId": ans['eventId']})
                ans = r.json()

                if ans['result']:
                    logger.success(f"Поток {self.thread} | Claim ChipPiece {piece} шт. | Hash - {hash}")
                    break
                else:
                    logger.warning(f"Поток {self.thread} | Ожидаю подтверждение [claim success] на сайте")
                    await asyncio.sleep(2)

        else:
            logger.error(f"Поток {self.thread} | Ошибка Claim ChipPieces: {ans}")

    async def mint_chip(self, chip):
        payload = {"addressThis":"0x00a9De8Af37a3179d7213426E78Be7DFb89F2b19",
                    "commodityToken":"0xe5116e725a8c1bF322dF6F5842b73102F3Ef0CeE",
                    "chainId":204,
                    "type":"chip"}

        r = await self.session.post("https://reiki.web3go.xyz/api/lottery/claim", json = payload)
        ans = r.json()

        if ans['result']:
            contract_address = '0x00a9De8Af37a3179d7213426E78Be7DFb89F2b19'
            sbt_address = '0xe5116e725a8c1bF322dF6F5842b73102F3Ef0CeE'
            args = (contract_address, sbt_address, self.address, 204, self.w3.to_int(hexstr=ans['nonce']), self.w3.to_bytes(hexstr=ans['signature']))

            data = await self.w3.eth.contract(contract_address, abi=chipVendorMachineContract).functions.safeBuyToken(*args).build_transaction({
                'from': self.address,
                'gasPrice': self.w3.to_wei('0.00001', 'gwei'), 
                'nonce': await self.w3.eth.get_transaction_count(self.address),
                'chainId': 204
                })
            data['gas'] = int((await self.w3.eth.estimate_gas(data))*1.01)
            hash = await self.send_txn(data)

            while True:
                r = await self.session.post("https://reiki.web3go.xyz/api/lottery/claimSuccess", json = {"eventId": ans['eventId']})
                ans = r.json()

                if ans['result']:
                    logger.success(f"Поток {self.thread} | Claim Chip {chip}шт. | Hash - {hash}")
                    break
                else:
                    logger.warning(f"Поток {self.thread} | Ожидаю подтверждение [claim success] на сайте")
                    await asyncio.sleep(3)

        else:
            logger.error(f"Поток {self.thread} | Ошибка Claim Chip: {ans}")

    async def check_balance(self, mult) -> str:
        balance_eth = self.w3.from_wei(await self.w3.eth.get_balance(self.address), 'ether')
        return True if balance_eth >= 0.0000115*mult else False
    
    async def sign_message(self, message: str):
        return self.w3.eth.account.sign_message(encode_defunct(text=message), self.private_key).signature.hex()

    async def send_txn(self, data: list, timeout: int = 120):
        sign_txn = self.w3.eth.account.sign_transaction(data, self.private_key)
        tx_hash = await self.w3.eth.send_raw_transaction(sign_txn.rawTransaction)
        await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        return tx_hash.hex()
    
    async def start(self):
        if not (await self.check_proxy() if USE_PROXY else 1):
            return 'badproxy'
        
        await self.login()

        piece, chip = await self.get_offchain()
        if await self.get_mint_info():
            chip = 0

        logger.info(f"Поток {self.thread} | Доступно: ChipPieces - {piece} шт., Chip - {chip} шт.")

        if piece or chip:
            mult = 2 if piece and chip else 1
            if not await self.check_balance(mult=mult):
                min_balance = 0.0000115 * mult
                logger.error(f"Поток {self.thread} | Недостаточный баланс, минимальный {min_balance:.7f} BNB | Address - {self.address}")
                return False
            else:
                await self.mint_piece(piece) if piece else None
                await self.mint_chip(chip) if chip else None

        logger.info(f"Поток {self.thread} | Работа с аккаунтом завершена.")


class TaskManager:
    def __init__(self) -> None:
        self.keys = self.get_file_data('private_key.txt')
        self.proxies = self.get_file_data('proxy.txt')

        self.lock = asyncio.Lock()
        self.err = [1, 1]
    
    def get_file_data(self, path: str) -> list:
        with open(path, 'r') as file:
            return [line.strip() for line in file.readlines() if line.strip()]
    
    def get_key(self) -> str:
        return self.keys.pop(0)
    
    def get_proxy(self) -> str:
        return self.proxies.pop(0) if self.proxies[0].startswith('http://') else 'http://' + self.proxies.pop(0)        
    
    async def initialization(self, thread: int):
        while True:
            async with self.lock:
                if self.keys:
                    key = self.get_key()
                else:
                    if self.err[0]:
                        self.err[0] = 0
                        return 'nokeys'
                    else: 
                        break

            if USE_PROXY:
                async with self.lock:
                    if self.proxies:
                        proxy = self.get_proxy()
                    else:
                        if self.err[1]:
                            self.err[1] = 0
                            return 'noproxy'
                        else:
                            self.keys.append(key)
                            break
            else:
                proxy = None
            
            result = await Web3GoMinter(thread, key, proxy).start()

            if result == 'badproxy':
                async with self.lock:
                    self.keys.append(key)


async def main():
    os.system('cls' if os.name == 'nt' else 'clear')

    logger.remove()

    logger.add(stdout, 
               colorize=True, 
               format="<cyan>{time:HH:mm:ss}</cyan> | <blue>{level:<7}</blue> | <level>{message}</level>", 
               level='INFO')

    print("Telegram: \033[34mhttps://t.me/oxcode1\033[0m\nПодпишись ^_^\n")
    threads = int(input("Введите количество потоков: "))

    mgr = TaskManager()
    tasks = []

    for thread in range(1, threads+1):
        tasks.append(asyncio.create_task(mgr.initialization(thread)))
    
    res = await asyncio.gather(*tasks)

    if 'nokeys' in res:
        logger.success("Список приватных ключей закончился! Все аккаунты отработаны. (Возможны ошибки, смотрите логи)")
    elif 'noproxy' in res:
        logger.error("Список прокси закончился! Не все аккаунты были обработаны.")


if __name__ == "__main__":
    asyncio.run(main())

