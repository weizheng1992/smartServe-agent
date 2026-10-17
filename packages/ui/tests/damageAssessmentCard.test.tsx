import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import type { DamageAssessmentData } from 'types';
import { DamageAssessmentCard } from '../src/components/chat/cards/DamageAssessmentCard';

// 2026-10-17 视觉加固零散项:绿色「成色良好」曾是 else 兜底 —— 任何脏数据都
// 渲染成安抚性绿标,对定责卡是误导性降级。钉死三档显式判定 + 未知值诚实降级。
const BASE: DamageAssessmentData = {
  damageLevel: 'minor',
  summary: '鞋面轻微划痕',
  confidence: 0.9,
  suggestedAction: 'human_review',
};

const renderCard = (data: DamageAssessmentData) => renderToString(<DamageAssessmentCard data={data} />);

describe('DamageAssessmentCard', () => {
  it('severe 渲染红色「严重破损」', () => {
    const html = renderCard({ ...BASE, damageLevel: 'severe' });
    expect(html).toContain('严重破损');
    expect(html).not.toContain('成色良好');
  });

  it('minor 渲染琥珀「瑕疵/轻微受损」', () => {
    const html = renderCard({ ...BASE, damageLevel: 'minor' });
    expect(html).toContain('瑕疵/轻微受损');
    expect(html).not.toContain('成色良好');
  });

  it('negligible 渲染绿色「成色良好」', () => {
    const html = renderCard({ ...BASE, damageLevel: 'negligible' });
    expect(html).toContain('成色良好');
  });

  it('未知 damageLevel 诚实降级「瑕疵/待核验」,严禁安抚性绿标', () => {
    const dirty = { ...BASE, damageLevel: 'bogus' } as unknown as DamageAssessmentData;
    const html = renderCard(dirty);
    expect(html).toContain('瑕疵/待核验');
    expect(html).not.toContain('成色良好');
  });
});
