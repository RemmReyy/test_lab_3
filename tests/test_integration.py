import uuid

import boto3
from app.eshop import Product, ShoppingCart, Order
import random
from services import ShippingService
from services.repository import ShippingRepository
from services.publisher import ShippingPublisher
from datetime import datetime, timedelta, timezone
from services.config import AWS_ENDPOINT_URL, AWS_REGION, SHIPPING_QUEUE
import pytest


@pytest.mark.parametrize("order_id, shipping_id", [
    ("order_1", "shipping_1"),
    ("order_i2hur2937r9", "shipping_1!!!!"),
    (8662354, 123456),
    (str(uuid.uuid4()), str(uuid.uuid4()))
])
def test_place_order_with_mocked_repo(mocker, order_id, shipping_id):
    mock_repo = mocker.Mock()
    mock_publisher = mocker.Mock()
    shipping_service = ShippingService(mock_repo, mock_publisher)

    mock_repo.create_shipping.return_value = shipping_id

    cart = ShoppingCart()
    cart.add_product(Product(
        available_amount=10,
        name='Product',
        price=random.random() * 10000),
        amount=9
    )

    order = Order(cart, shipping_service, order_id)
    due_date = datetime.now(timezone.utc) + timedelta(seconds=3)
    actual_shipping_id = order.place_order(
        ShippingService.list_available_shipping_type()[0],
        due_date=due_date
    )

    assert actual_shipping_id == shipping_id, "Actual shipping id must be equal to mock return value"

    mock_repo.create_shipping.assert_called_with(ShippingService.list_available_shipping_type()[0], ["Product"], order_id, shipping_service.SHIPPING_CREATED, due_date)
    mock_publisher.send_new_shipping.assert_called_with(shipping_id)


def test_place_order_with_unavailable_shipping_type_fails(dynamo_resource):
    shipping_service = ShippingService(ShippingRepository(), ShippingPublisher())
    cart = ShoppingCart()
    cart.add_product(Product(
        available_amount=10,
        name='Product',
        price=random.random() * 10000),
        amount=9
    )
    order = Order(cart, shipping_service)
    shipping_id = None

    with pytest.raises(ValueError) as excinfo:
        shipping_id = order.place_order(
            "Новий тип доставки",
            due_date=datetime.now(timezone.utc) + timedelta(seconds=3)
        )
    assert shipping_id is None, "Shipping id must not be assigned"
    assert "Shipping type is not available" in str(excinfo.value)



def test_when_place_order_then_shipping_in_queue(dynamo_resource):
    shipping_service = ShippingService(ShippingRepository(), ShippingPublisher())
    cart = ShoppingCart()

    cart.add_product(Product(
        available_amount=10,
        name='Product',
        price=random.random() * 10000),
        amount=9
    )

    order = Order(cart, shipping_service)
    shipping_id = order.place_order(
        ShippingService.list_available_shipping_type()[0],
        due_date=datetime.now(timezone.utc) + timedelta(minutes=1)
    )

    sqs_client = boto3.client(
        "sqs",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_REGION
    )
    queue_url = sqs_client.get_queue_url(QueueName=SHIPPING_QUEUE)["QueueUrl"]
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10
    )

    messages = response.get("Messages", [])
    assert len(messages) == 1, "Expected 1 SQS message"

    body = messages[0]["Body"]
    assert shipping_id == body


def test_create_order(order):
    assert order.order_id is not None
    assert len(order.cart.products) > 0


def test_list_available_shipping_types(shipping_service):
    expected_types = ["Нова Пошта", "Укр Пошта", "Meest Express", "Самовивіз"]
    assert shipping_service.list_available_shipping_type() == expected_types


def test_place_order_success(order):
    shipping_type = "Нова Пошта"
    due_date = datetime.now(timezone.utc) + timedelta(days=1)
    shipping_id = order.place_order(shipping_type, due_date=due_date)

    assert shipping_id is not None


def test_place_order_invalid_shipping_type(order):
    with pytest.raises(ValueError, match="Shipping type is not available"):
        order.place_order("Fake Express", datetime.now(timezone.utc) + timedelta(days=1))


def test_place_order_past_due_date(order):
    past_due_date = datetime.now(timezone.utc) - timedelta(days=1)
    with pytest.raises(ValueError, match="Shipping due datetime must be greater than datetime now"):
        order.place_order("Нова Пошта", past_due_date)


def test_check_shipping_status(order, shipping_service):
    shipping_type = "Укр Пошта"
    due_date = datetime.now(timezone.utc) + timedelta(days=1)
    shipping_id = order.place_order(shipping_type, due_date=due_date)

    status = shipping_service.check_status(shipping_id)
    assert status == shipping_service.SHIPPING_IN_PROGRESS


def test_complete_shipping(order, shipping_service):
    shipping_type = "Meest Express"
    due_date = datetime.now(timezone.utc) + timedelta(days=1)
    shipping_id = order.place_order(shipping_type, due_date=due_date)

    response = shipping_service.complete_shipping(shipping_id)
    assert response["HTTPStatusCode"] == 200


def test_fail_shipping(order, shipping_service):
    shipping_type = "Самовивіз"
    future_due_date = datetime.now(timezone.utc) + timedelta(days=1)
    shipping_id = order.place_order(shipping_type, due_date=future_due_date)

    past_due_date = datetime.now(timezone.utc) - timedelta(days=1)
    shipping_service.repository.table.update_item(
        Key={"shipping_id": shipping_id},
        UpdateExpression="SET due_date = :new_due_date",
        ExpressionAttributeValues={":new_due_date": past_due_date.isoformat()}
    )

    response = shipping_service.fail_shipping(shipping_id)

    assert response["HTTPStatusCode"] == 200


def test_product_quantity_after_order(order):
    product = list(order.cart.products.keys())[0]
    initial_quantity = product.available_amount

    order.place_order("Нова Пошта", datetime.now(timezone.utc) + timedelta(days=1))

    assert product.available_amount < initial_quantity


def test_shipping_message_sent(mocker, shopping_cart):
    mock_publisher = mocker.Mock()
    mock_publisher.send_new_shipping.return_value = "mock_message_id"

    shipping_service = ShippingService(ShippingRepository(), mock_publisher)

    order = Order(cart=shopping_cart, shipping_service=shipping_service, order_id=str(uuid.uuid4()))

    shipping_type = "Нова Пошта"
    due_date = datetime.now(timezone.utc) + timedelta(days=1)

    shipping_id = order.place_order(shipping_type, due_date=due_date)

    mock_publisher.send_new_shipping.assert_called_once_with(shipping_id)