"""Count actual ModelGateway attempts, including injected structured-output runners."""
from ..llm import ModelGateway


def counted_gateway(settings, injected, before_call, operation_id):
    if injected is None:
        return ModelGateway(settings, before_call=before_call, operation_id=operation_id)
    if isinstance(injected, ModelGateway):
        return ModelGateway(injected.settings, runner=injected.runner, sleep=injected.sleep,
                            before_call=before_call, operation_id=operation_id)

    class TestGatewayAdapter:
        """Non-provider test gateways implement one request per generate invocation."""
        async def generate(self, schema, prompt, check=None):
            await before_call()
            return await injected.generate(schema, prompt, check)
    return TestGatewayAdapter()
