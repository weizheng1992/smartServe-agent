import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { NextResponse } from 'next/server';

export async function GET() {
  try {
    const products = await MerchantDomainService.searchProducts({ limit: 20 });
    return NextResponse.json({ success: true, products });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
