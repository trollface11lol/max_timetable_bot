import aiohttp
from grpc import personal_schedule_pb2 as pb2
import struct


class ScheduleWebClient:
    def __init__(self, token: str):
        self.base_url = "https://schedule-of.mirea.ru"
        self.token = token
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/grpc-web+proto",
            "X-Grpc-Web": "1",
        }

    def _encode_grpc_web_message(self, message_data):
        """Кодирует сообщение в gRPC-Web формат"""
        message_length = len(message_data)
        prefix = struct.pack('>BI', 0x00, message_length)
        return prefix + message_data

    def _decode_grpc_web_message(self, response_data):
        """Декодирует gRPC-Web ответ"""
        if len(response_data) < 5 or response_data[0] != 0x00:
            return response_data

        message_length = struct.unpack('>I', response_data[1:5])[0]
        if len(response_data) >= 5 + message_length:
            return response_data[5:5 + message_length]

        return response_data[5:]

    async def _make_grpc_web_request(self, method_name: str, request_msg):
        """Универсальный метод для gRPC-Web запросов"""
        url = f"{self.base_url}/rtu.schedule.api.PersonalScheduleService/{method_name}"

        request_data = request_msg.SerializeToString()
        grpc_web_data = self._encode_grpc_web_message(request_data)

        async with self.session.post(url, data=grpc_web_data, headers=self._get_headers()) as response:
            if response.status != 200:
                text = await response.text()
                raise Exception(f"HTTP {response.status}: {text}")

            raw_data = await response.read()
            return self._decode_grpc_web_message(raw_data)

    async def get_subscribed_schedules(self):
        """Получение расписаний, на которые есть подписка"""
        request = pb2.GetSubscribedSchedulesRequest()
        response_data = await self._make_grpc_web_request("GetSubscribedSchedules", request)

        response = pb2.GetSubscribedSchedulesResponse()
        response.ParseFromString(response_data)
        return response

    async def update_subscribed_schedules(self, schedule_ids):
        """Обновление подписок на расписания"""
        request = pb2.UpdateSubscribedSchedulesRequest()
        request.schedule_id.extend(schedule_ids)

        response_data = await self._make_grpc_web_request("UpdateSubscribedSchedules", request)

        response = pb2.UpdateSubscribedSchedulesResponse()
        response.ParseFromString(response_data)
        return response

    async def get_personal_schedule_updates(self, schedule_id):
        """Получение обновлений по расписанию"""
        request = pb2.GetPersonalScheduleUpdatesRequest(schedule_id=schedule_id)
        response_data = await self._make_grpc_web_request("GetPersonalScheduleUpdates", request)

        response = pb2.GetPersonalScheduleUpdatesResponse()
        response.ParseFromString(response_data)
        return response

    async def accept_schedule_updates(self, schedule_id, snapshot_id):
        """Принятие обновлений"""
        request = pb2.AcceptScheduleUpdatesRequest(
            schedule_id=schedule_id,
            snapshot_id=snapshot_id
        )
        response_data = await self._make_grpc_web_request("AcceptScheduleUpdates", request)

        response = pb2.AcceptScheduleUpdatesResponse()
        response.ParseFromString(response_data)
        return response

    async def get_schedule_title(self, schedule_id):
        """Получение названия расписания"""
        request = pb2.GetScheduleTitleRequest(schedule_id=schedule_id)
        response_data = await self._make_grpc_web_request("GetScheduleTitle", request)

        response = pb2.GetScheduleTitleResponse()
        response.ParseFromString(response_data)
        return response

    async def get_wrapped_schedule(self, schedule_id):
        """Получение полного расписания"""
        request = pb2.GetWrappedScheduleRequest(schedule_id=schedule_id)
        response_data = await self._make_grpc_web_request("GetWrappedSchedule", request)

        response = pb2.GetWrappedScheduleResponse()
        response.ParseFromString(response_data)
        return response


def create_schedule_id(schedule_type, schedule_id):
    """Создание ScheduleId"""
    return pb2.ScheduleId(
        schedule_type=schedule_type,
        schedule_id=schedule_id
    )