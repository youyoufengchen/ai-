"""
第三方平台商品适配器
支持从抖音、淘宝、快手等平台同步直播间商品
"""
import json
import logging
import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import aiohttp

logger = logging.getLogger("server")


@dataclass
class PlatformProduct:
    """统一的平台商品数据结构"""
    platform_id: str           # 平台商品ID
    platform: str              # 平台名称 douyin/taobao/kuaishou等
    name: str                  # 商品名称
    price: float               # 价格
    original_price: float      # 原价
    stock: int                 # 库存
    category: str              # 分类
    image_url: str             # 主图URL
    detail_url: str            # 商品详情页
    status: str               # 状态 on_sale/off_shelf/out_of_stock
    create_time: datetime      # 创建时间
    extra: Dict[str, Any]     # 平台特有数据


class BasePlatformAdapter:
    """平台适配器基类"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.enabled = config.get('enabled', False)
        self.platform_name = config.get('name', '未知平台')
    
    async def authenticate(self) -> bool:
        """验证平台凭证是否有效"""
        raise NotImplementedError
    
    async def get_live_products(self, room_id: str) -> List[PlatformProduct]:
        """获取直播间商品列表"""
        raise NotImplementedError
    
    async def get_product_detail(self, product_id: str) -> Optional[PlatformProduct]:
        """获取商品详情"""
        raise NotImplementedError
    
    async def sync_to_local(self, products: List[PlatformProduct]) -> Dict:
        """同步商品到本地系统"""
        raise NotImplementedError


class DouyinAdapter(BasePlatformAdapter):
    """抖音开放平台商品适配器"""
    
    API_BASE = "https://open.douyin.com"
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.app_id = config.get('app_id', '')
        self.app_secret = config.get('app_secret', '')
        self.access_token = config.get('access_token', '')
        self.room_id = config.get('room_id', '')
    
    async def authenticate(self) -> bool:
        """验证抖音access_token"""
        if not self.access_token:
            logger.warning("[Douyin] 缺少access_token")
            return False
        
        url = f"{self.API_BASE}/oauth/client_token/"
        params = {
            "client_key": self.app_id,
            "client_secret": self.app_secret,
            "grant_type": "client_credential"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    data = await resp.json()
                    if data.get('data', {}).get('access_token'):
                        self.access_token = data['data']['access_token']
                        logger.info("[Douyin] 认证成功，获取到新access_token")
                        return True
                    else:
                        logger.error(f"[Douyin] 认证失败: {data}")
                        return False
        except Exception as e:
            logger.error(f"[Douyin] 认证异常: {e}")
            return False
    
    async def get_live_products(self, room_id: str = None) -> List[PlatformProduct]:
        """
        获取抖音直播间商品列表
        API: /goodlife/v1/live/product/query
        文档: https://open.douyin.com/platform/doc
        """
        if not self.access_token:
            if not await self.authenticate():
                return []
        
        room_id = room_id or self.room_id
        if not room_id:
            logger.warning("[Douyin] 未配置room_id")
            return []
        
        url = f"{self.API_BASE}/goodlife/v1/live/product/query"
        headers = {
            "access-token": self.access_token,
            "Content-Type": "application/json"
        }
        params = {
            "room_id": room_id,
            "cursor": 0,
            "count": 100
        }
        
        products = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=15) as resp:
                    data = await resp.json()
                    
                    if data.get('data', {}).get('products'):
                        for item in data['data']['products']:
                            product = self._convert_product(item)
                            if product:
                                products.append(product)
                        
                        logger.info(f"[Douyin] 获取到 {len(products)} 个商品")
                    else:
                        logger.warning(f"[Douyin] 获取商品失败: {data}")
                        
        except Exception as e:
            logger.error(f"[Douyin] 获取商品异常: {e}")
        
        return products
    
    def _convert_product(self, item: Dict) -> Optional[PlatformProduct]:
        """转换抖音商品数据到统一格式"""
        try:
            product_id = item.get('product_id', '')
            return PlatformProduct(
                platform_id=product_id,
                platform='douyin',
                name=item.get('name', '未知商品'),
                price=float(item.get('price', 0)) / 100,  # 抖音价格单位是分
                original_price=float(item.get('market_price', 0)) / 100,
                stock=int(item.get('stock', 0)),
                category=item.get('category_name', '未分类'),
                image_url=item.get('cover', ''),
                detail_url=f"https://web.jinritemai.com/detail/{product_id}",
                status=self._map_status(item.get('status', '')),
                create_time=datetime.now(),
                extra=item
            )
        except Exception as e:
            logger.error(f"[Douyin] 商品数据转换失败: {e}")
            return None
    
    def _map_status(self, status: str) -> str:
        """映射抖音状态到统一状态"""
        status_map = {
            '1': 'on_sale',      # 上架
            '2': 'off_shelf',    # 下架
            '3': 'out_of_stock', # 售罄
        }
        return status_map.get(status, 'unknown')


class TaobaoAdapter(BasePlatformAdapter):
    """
    淘宝直播商品适配器
    
    淘宝开放平台对接说明：
    - 需在淘宝开放平台申请直播订阅权限：https://open.taobao.com
    - 调用API：taobao.tbk.item.info.get / taobao.miniapp.media.upload
    - 需要session_key（用户授权后获取）
    """
    
    API_BASE = "https://gw-api.taobao.com/router/rest"
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.app_key = config.get('app_key', '')
        self.app_secret = config.get('app_secret', '')
        self.session_key = config.get('session_key', '')
    
    def _is_configured(self) -> bool:
        """检查是否已完整配置"""
        return bool(self.app_key and self.app_secret and self.session_key)
    
    async def authenticate(self) -> bool:
        """验证淘宝session_key有效性"""
        if not self._is_configured():
            logger.warning("[Taobao] 凭证未配置：需要app_key/app_secret/session_key")
            return False
        # 实际生产环境应调用 taobao.user.seller.get 验证 session_key
        return True
    
    async def get_live_products(self, room_id: str = None) -> List[PlatformProduct]:
        """获取淘宝直播间商品"""
        if not self._is_configured():
            logger.info("[Taobao] 凭证未配置，跳过商品同步")
            return []
        
        # 占位：实际接入需要按淘宝开放平台API签名规范实现
        # 推荐使用淘宝官方 SDK：pip install taobao-sdk
        logger.warning(
            "[Taobao] 商品API需要淘宝开放平台正式接入。"
            "请参考 https://open.taobao.com/api.htm 实现签名调用"
        )
        return []


class KuaishouAdapter(BasePlatformAdapter):
    """
    快手直播商品适配器
    
    快手开放平台对接说明：
    - 需在快手小店开放平台申请直播订阅权限
    - 文档：https://open.kuaishou.com/platform/openApi
    - 使用OAuth2授权 + access_token调用
    """
    
    API_BASE = "https://open.kuaishou.com/openapi"
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.app_id = config.get('app_id', '')
        self.app_secret = config.get('app_secret', '')
        self.access_token = config.get('access_token', '')
    
    def _is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)
    
    async def authenticate(self) -> bool:
        """获取/刷新access_token"""
        if not self._is_configured():
            logger.warning("[Kuaishou] 凭证未配置：需要app_id/app_secret")
            return False
        return True
    
    async def get_live_products(self, room_id: str = None) -> List[PlatformProduct]:
        """获取快手直播间商品"""
        if not self._is_configured():
            logger.info("[Kuaishou] 凭证未配置，跳过商品同步")
            return []
        
        logger.warning(
            "[Kuaishou] 商品API需要快手小店开放平台正式接入。"
            "请参考 https://open.kuaishou.com/platform/openApi 实现"
        )
        return []


class PlatformProductManager:
    """平台商品管理器"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._init_adapters()
    
    def _init_adapters(self):
        """初始化所有启用的平台适配器"""
        platform_configs = self.config.get('platforms', {})
        
        adapter_classes = {
            'douyin': DouyinAdapter,
            'taobao': TaobaoAdapter,
            'kuaishou': KuaishouAdapter,
        }
        
        for platform, cfg in platform_configs.items():
            if platform.startswith('_'):  # 跳过内部字段
                continue
                
            if cfg.get('enabled') and platform in adapter_classes:
                try:
                    adapter = adapter_classes[platform](cfg)
                    self.adapters[platform] = adapter
                    logger.info(f"[PlatformManager] 初始化 {platform} 适配器")
                except Exception as e:
                    logger.error(f"[PlatformManager] 初始化 {platform} 失败: {e}")
    
    async def sync_platform_products(self, platform: str, room_id: str = None) -> Dict:
        """同步指定平台的商品"""
        adapter = self.adapters.get(platform)
        if not adapter:
            return {
                'success': False,
                'error': f'平台 {platform} 未启用或未配置'
            }
        
        # 获取平台商品
        products = await adapter.get_live_products(room_id)
        
        if not products:
            return {
                'success': True,
                'count': 0,
                'products': [],
                'message': '未获取到商品或平台返回空列表'
            }
        
        # 转换为本地格式
        local_products = [self._convert_to_local(p) for p in products]
        
        return {
            'success': True,
            'count': len(local_products),
            'platform': platform,
            'products': local_products,
            'message': f'成功获取 {len(local_products)} 个商品'
        }
    
    def _convert_to_local(self, product: PlatformProduct) -> Dict:
        """将平台商品转换为本地SKU格式"""
        return {
            'id': f"{product.platform}_{product.platform_id}",
            'name': product.name,
            'platform_id': product.platform_id,
            'platform': product.platform,
            'price': product.price,
            'original_price': product.original_price,
            'stock': product.stock,
            'category': product.category,
            'image_url': product.image_url,
            'detail_url': product.detail_url,
            'status': product.status,
            'sync_time': datetime.now().isoformat(),
            'extra': product.extra
        }
    
    def get_available_platforms(self) -> List[Dict]:
        """获取所有可用平台列表"""
        return [
            {
                'id': pid,
                'name': adapter.platform_name,
                'enabled': adapter.enabled,
                'room_id': getattr(adapter, 'room_id', '')
            }
            for pid, adapter in self.adapters.items()
        ]
    
    async def test_connection(self, platform: str) -> Dict:
        """测试平台连接"""
        adapter = self.adapters.get(platform)
        if not adapter:
            return {'success': False, 'error': '平台未配置'}
        
        try:
            result = await adapter.authenticate()
            return {
                'success': result,
                'message': '连接成功' if result else '认证失败'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


# 模拟数据生成器（用于开发和测试）
class MockPlatformAdapter(BasePlatformAdapter):
    """模拟平台适配器，用于测试"""
    
    async def get_live_products(self, room_id: str = None) -> List[PlatformProduct]:
        """返回模拟商品数据"""
        await asyncio.sleep(1)  # 模拟网络延迟
        
        mock_products = [
            PlatformProduct(
                platform_id='123456',
                platform='douyin',
                name='【抖音爆款】西湖龙井明前茶',
                price=168.00,
                original_price=298.00,
                stock=999,
                category='茶叶',
                image_url='https://example.com/tea.jpg',
                detail_url='https://example.com/detail/123456',
                status='on_sale',
                create_time=datetime.now(),
                extra={'source': 'mock'}
            ),
            PlatformProduct(
                platform_id='789012',
                platform='douyin',
                name='【限时特惠】铁观音礼盒装',
                price=128.00,
                original_price=198.00,
                stock=500,
                category='茶叶',
                image_url='https://example.com/tea2.jpg',
                detail_url='https://example.com/detail/789012',
                status='on_sale',
                create_time=datetime.now(),
                extra={'source': 'mock'}
            ),
            PlatformProduct(
                platform_id='345678',
                platform='douyin',
                name='【新品上市】普洱熟茶饼',
                price=258.00,
                original_price=358.00,
                stock=200,
                category='茶叶',
                image_url='https://example.com/tea3.jpg',
                detail_url='https://example.com/detail/345678',
                status='on_sale',
                create_time=datetime.now(),
                extra={'source': 'mock'}
            ),
        ]
        
        return mock_products
    
    async def authenticate(self) -> bool:
        return True


# 创建管理器实例的工厂函数
def create_platform_product_manager(config_manager):
    """创建平台商品管理器"""
    return PlatformProductManager(config_manager)
