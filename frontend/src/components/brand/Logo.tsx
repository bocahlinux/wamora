import logoHorizontalDark from '../../assets/brand/wamora-logo-horizontal-dark.png';
import logoHorizontalLight from '../../assets/brand/wamora-logo-horizontal-light.png';
import markDark from '../../assets/brand/wamora-mark-dark.png';
import markPrimary from '../../assets/brand/wamora-mark-primary.png';
import { useTheme } from '../../theme/ThemeContext';

// wamora-design-assets design spec Section 3: horizontal logo when there is
// enough horizontal space, compact mark otherwise; a dark-surface variant
// exists for each so the logo is never placed on a background it wasn't
// designed for (spec: "Do not recolor the logo arbitrarily").
//
// Source assets are reference-quality crops from the supplied design
// board (wamora-design-assets/assets/brand/, wamora-design-assets/assets/reference/wamora-frontend-reference.png)
// — the design package itself says these are not yet approved SVG
// masters (ASSET-INTEGRATION-GUIDE.md Section 4); using them as-is here
// is intentional and documented, not a substitute for that future step.

interface LogoProps {
  variant?: 'horizontal' | 'mark';
  onDark?: boolean;
  height?: number;
}

export function Logo({ variant = 'horizontal', onDark, height }: LogoProps) {
  const { resolvedTheme } = useTheme();
  const dark = onDark ?? resolvedTheme === 'dark';

  if (variant === 'mark') {
    return (
      <img
        src={dark ? markDark : markPrimary}
        alt="WAMORA"
        height={height ?? 32}
        style={{ height: height ?? 32, width: 'auto' }}
      />
    );
  }

  return (
    <img
      src={dark ? logoHorizontalDark : logoHorizontalLight}
      alt="WAMORA — WhatsApp Operations & Monitoring"
      height={height ?? 32}
      style={{ height: height ?? 32, width: 'auto' }}
    />
  );
}
