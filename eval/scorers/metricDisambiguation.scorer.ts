import { MetricSemanticResolver } from '../../packages/tools/src/metricRegistry';

export default function (output: string, context: any) {
  try {
    const input = context.vars?.input;
    const expectedMetric = context.vars?.expectedMetric;
    const expectedAmbiguity = context.vars?.expectedAmbiguity;
    const expectedConflictGroup = context.vars?.expectedConflictGroup;

    if (!input || !expectedMetric) {
      return {
        pass: true,
        score: 1.0,
        reason: 'No input or expectedMetric specified, skipping metric disambiguation check',
      };
    }

    const resolution = MetricSemanticResolver.resolve(input);

    const isMetricMatch = resolution.primaryMetric.key === expectedMetric;
    const isAmbiguityMatch = expectedAmbiguity === undefined || resolution.hasAmbiguity === expectedAmbiguity;
    const isConflictGroupMatch =
      expectedConflictGroup === undefined || resolution.conflictMetrics.some((m) => m.key === expectedConflictGroup);

    if (isMetricMatch && isAmbiguityMatch && isConflictGroupMatch) {
      return {
        pass: true,
        score: 1.0,
        reason: `Successfully resolved metric '${resolution.primaryMetric.key}' (Ambiguity: ${resolution.hasAmbiguity}) matching expectation '${expectedMetric}'.`,
      };
    }

    return {
      pass: false,
      score: 0.0,
      reason: `Metric mismatch. Expected: metric=${expectedMetric}, ambiguity=${expectedAmbiguity}. Got: metric=${resolution.primaryMetric.key}, ambiguity=${resolution.hasAmbiguity}`,
    };
  } catch (err: any) {
    return {
      pass: false,
      score: 0.0,
      reason: `Error in metricDisambiguation scorer: ${err.message}`,
    };
  }
}
