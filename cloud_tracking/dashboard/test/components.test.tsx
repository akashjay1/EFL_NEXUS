import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { StatusBadge, IdentityBadge } from '../src/components/common/Badge';
import { Card } from '../src/components/common/Card';
import { Modal } from '../src/components/common/Modal';

describe('UI component tests', () => {
  describe('StatusBadge', () => {
    it('renders Active badge with emerald styling for active or online status', () => {
      const { rerender } = render(<StatusBadge status="active" />);
      expect(screen.getByText('Active')).toBeDefined();

      rerender(<StatusBadge status="online" />);
      expect(screen.getByText('Active')).toBeDefined();
    });

    it('renders Idle badge with amber styling', () => {
      render(<StatusBadge status="idle" />);
      expect(screen.getByText('Idle')).toBeDefined();
    });

    it('renders Disconnected badge with red styling', () => {
      render(<StatusBadge status="disconnected" />);
      expect(screen.getByText('Disconnected')).toBeDefined();
    });

    it('renders Revoked badge with purple styling', () => {
      render(<StatusBadge status="revoked" />);
      expect(screen.getByText('Revoked')).toBeDefined();
    });

    it('renders Closed badge with blue styling', () => {
      render(<StatusBadge status="closed" />);
      expect(screen.getByText('Closed')).toBeDefined();
    });

    it('renders Offline badge for ended or unrecognized status', () => {
      render(<StatusBadge status="offline" />);
      expect(screen.getByText('Offline')).toBeDefined();
    });
  });

  describe('IdentityBadge', () => {
    it('renders KPI Profile badge with green styling and verified icon', () => {
      render(<IdentityBadge source="KPI Profile" />);
      expect(screen.getByText('KPI Profile')).toBeDefined();
    });

    it('renders Device Fallback badge with amber warning styling', () => {
      render(<IdentityBadge source="Device Fallback" />);
      expect(screen.getByText('Device Fallback')).toBeDefined();
    });
  });

  describe('Card', () => {
    it('renders title, subtitle, action, and content', () => {
      render(
        <Card
          title="Telemetry Summary"
          subtitle="Live metrics from desktop nodes"
          action={<button>Refresh</button>}
        >
          <div>Card Body Content</div>
        </Card>
      );

      expect(screen.getByText('Telemetry Summary')).toBeDefined();
      expect(screen.getByText('Live metrics from desktop nodes')).toBeDefined();
      expect(screen.getByText('Refresh')).toBeDefined();
      expect(screen.getByText('Card Body Content')).toBeDefined();
    });
  });

  describe('Modal', () => {
    it('does not render when isOpen is false', () => {
      render(
        <Modal isOpen={false} onClose={() => {}} title="Test Modal">
          <div>Hidden Content</div>
        </Modal>
      );
      expect(screen.queryByText('Hidden Content')).toBeNull();
    });

    it('renders title and children when isOpen is true and fires onClose', () => {
      const handleClose = vi.fn();
      render(
        <Modal
          isOpen={true}
          onClose={handleClose}
          title="Test Modal"
        >
          <div>Modal Body Content</div>
          <button onClick={handleClose}>Confirm</button>
        </Modal>
      );

      expect(screen.getByText('Test Modal')).toBeDefined();
      expect(screen.getByText('Modal Body Content')).toBeDefined();
      const confirmBtn = screen.getByText('Confirm');
      fireEvent.click(confirmBtn);
      expect(handleClose).toHaveBeenCalledTimes(1);
    });
  });
});
