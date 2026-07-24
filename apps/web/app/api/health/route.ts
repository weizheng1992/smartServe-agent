import { NextRequest, NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({
    status: 'healthy',
    message: 'E-Commerce Agent Platform API is ready.',
    date: '2026-07-16',
  });
}
