using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using KorberAuditShip.Models;
using KorberAuditShip.ViewModels;

namespace KorberAuditShip.Views;

/// <summary>
/// Interaction logic for KorberAuditShipView UserControl module.
/// </summary>
public partial class KorberAuditShipView : UserControl
{
    public MainViewModel? ViewModel => DataContext as MainViewModel;

    public KorberAuditShipView()
    {
        InitializeComponent();
    }

    public void Shutdown()
    {
        ViewModel?.ExecuteStopAutomation();
    }

    private void AuditDataGrid_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (ViewModel is null)
        {
            return;
        }

        ViewModel.HandleTableMouseWheel(e.Delta);
        e.Handled = true;
    }

    private void AuditDataGrid_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        CopyCurrentCell();
    }

    private void AuditDataGrid_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            CopyCurrentCell();
            e.Handled = true;
        }
    }

    private void GoToRowBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && ViewModel is not null && ViewModel.GoToRowCommand.CanExecute(null))
        {
            ViewModel.GoToRowCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void CopyCurrentCell()
    {
        if (ViewModel is null)
        {
            return;
        }

        DataGridCellInfo cell = AuditDataGrid.CurrentCell;
        if (cell.Item is not AuditShipRow row || cell.Column is null)
        {
            return;
        }

        int columnIndex = AuditDataGrid.Columns.IndexOf(cell.Column);
        string? value = columnIndex switch
        {
            0 => row.WhId,
            1 => row.LoadId,
            2 => row.GatePassId,
            3 => row.DoorLocation,
            4 => row.LoadAuditStatus,
            5 => row.ShippingStatus,
            _ => null
        };

        ViewModel.CopyCellValue(value);
    }
}
