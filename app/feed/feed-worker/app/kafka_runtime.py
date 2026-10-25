"""Commit Kafka offsets only after successful event processing."""


def process_and_commit(consumer, msg, handler):
    result = handler(msg.value(), msg.key())
    # Never continue to later messages after a failure and then commit past it.
    partitions = consumer.commit(message=msg, asynchronous=False)
    for partition in partitions or []:
        if partition.error:
            raise RuntimeError("Kafka offset commit failed")
    return result
