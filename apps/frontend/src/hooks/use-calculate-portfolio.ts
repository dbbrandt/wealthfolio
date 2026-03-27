import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "@wealthfolio/ui/components/ui/use-toast";
import { updatePortfolio, recalculatePortfolio, rebuildPortfolio } from "@/adapters";
import { logger } from "@/adapters";

export function useUpdatePortfolioMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updatePortfolio,
    onError: (error) => {
      queryClient.invalidateQueries();
      toast({
        title: "Failed to update portfolio data.",
        description: "Please try again or report an issue if the problem persists.",
        variant: "destructive",
      });
      logger.error(`Error calculating historical data: ${String(error)}`);
    },
  });
}

export function useRecalculatePortfolioMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: recalculatePortfolio,
    onError: (error) => {
      queryClient.invalidateQueries();
      toast({
        title: "Failed to recalculate portfolio.",
        description: "Please try again or report an issue if the problem persists.",
        variant: "destructive",
      });
      console.warn("Error recalculating portfolio:", error);
      logger.error(`Error recalculating portfolio: ${String(error)}`);
    },
  });
}

/**
 * Rebuilds portfolio without syncing market data.
 * Much faster - use when you've fixed activity data and just need to recalculate.
 */
export function useRebuildPortfolioMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountIds?: string[]) => rebuildPortfolio(accountIds),
    onError: (error) => {
      queryClient.invalidateQueries();
      toast({
        title: "Failed to rebuild portfolio.",
        description: "Please try again or report an issue if the problem persists.",
        variant: "destructive",
      });
      logger.error(`Error rebuilding portfolio: ${String(error)}`);
    },
  });
}
