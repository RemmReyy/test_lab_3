import pytest
import boto3
import uuid

from app.eshop import ShoppingCart, Product, Order
from services import ShippingService
from services.config import *
from services.db import get_dynamodb_resource
from dotenv import load_dotenv

from services.publisher import ShippingPublisher
from services.repository import ShippingRepository


@pytest.fixture(scope="session", autouse=True)
def load_env():
    load_dotenv()

@pytest.fixture(scope="session", autouse=True)
def setup_localstack_resources():
    dynamo_client = boto3.client(
        "dynamodb",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_REGION
    )
    existing_tables = dynamo_client.list_tables()["TableNames"]
    if SHIPPING_TABLE_NAME not in existing_tables:
        dynamo_client.create_table(
            TableName=SHIPPING_TABLE_NAME,
            KeySchema=[{"AttributeName": "shipping_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "shipping_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamo_client.get_waiter("table_exists").wait(TableName=SHIPPING_TABLE_NAME)
    sqs_client = boto3.client(
        "sqs",
        endpoint_url=AWS_ENDPOINT_URL, region_name=AWS_REGION
    )
    response = sqs_client.create_queue(QueueName=SHIPPING_QUEUE)
    queue_url = response["QueueUrl"]

    yield  # Всі тести йдуть тут

    dynamo_client.delete_table(TableName=SHIPPING_TABLE_NAME)
    sqs_client.delete_queue(QueueUrl=queue_url)


@pytest.fixture
def dynamo_resource():
    return get_dynamodb_resource()


@pytest.fixture
def shipping_service():
    return ShippingService(ShippingRepository(), ShippingPublisher())


@pytest.fixture
def shopping_cart():
    cart = ShoppingCart()
    cart.add_product(Product(name="Laptop", price=1000.0, available_amount=5), amount=1)
    cart.add_product(Product(name="Phone", price=500.0, available_amount=10), amount=2)
    return cart


@pytest.fixture
def order(shopping_cart, shipping_service):
    return Order(cart=shopping_cart, shipping_service=shipping_service, order_id=str(uuid.uuid4()))
