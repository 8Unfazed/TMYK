import type { ReactNode } from 'react';

type SlideCommitProps = {
  label?: string;
  doneLabel?: string;
  errorLabel?: string;
  onConfirm?: () => unknown | Promise<unknown>;
  onDone?: () => void;
  onError?: (error: unknown) => void;
  trackColor?: string;
  handleColor?: string;
  successColor?: string;
  dangerColor?: string;
  width?: number;
  height?: number;
  radius?: number;
  speed?: number;
  returnBounce?: number;
  landingDip?: number;
  holdMs?: number;
  disabled?: boolean;
  icon?: ReactNode;
  className?: string;
};

export default function SlideCommit(props: SlideCommitProps): JSX.Element;
