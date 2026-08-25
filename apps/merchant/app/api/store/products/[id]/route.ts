import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (!id) {
      return NextResponse.json({ success: false, error: '商品 ID 不能为空' }, { status: 400 });
    }

    const product = await MerchantDomainService.getProductDetail(id);
    if (!product) {
      return NextResponse.json({ success: false, error: `商品 [${id}] 未找到或已下架` }, { status: 404 });
    }

    return NextResponse.json({ success: true, product });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
