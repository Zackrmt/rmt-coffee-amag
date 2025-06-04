/**
 * imageGenerator.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:55:21 UTC
 */

const { createCanvas, loadImage } = require('canvas');

class ImageGenerator {
    constructor() {
        this.width = 1080;      // Instagram story width
        this.height = 1350;     // Instagram story height (4:5 aspect ratio)
    }

    // Design 2: Modern Split Layout
    async generateDesign2(stats) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // White background
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header (very big and centered)
        ctx.font = 'bold 120px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'center';
        ctx.fillText('MTLE 2025', this.width/2, 150);

        // Split layout with gradient background
        const gradient = ctx.createLinearGradient(0, 300, 0, this.height);
        gradient.addColorStop(0, '#f8f9fa');
        gradient.addColorStop(1, '#e9ecef');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 300, this.width, this.height);

        // Study stats
        ctx.font = 'bold 48px Arial';
        ctx.fillStyle = '#2C3E50';
        ctx.fillText(`Subject: ${stats.subject}`, this.width/2, 350);
        
        // Progress circle
        this.drawProgressCircle(ctx, this.width/2, 600, 200, stats.percentage);

        // Time statistics
        this.drawTimeStats(ctx, stats, 850);

        return canvas.toBuffer('image/png');
    }

    // Design 5: Dark Theme with Neon Accents
    async generateDesign5(stats) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // Dark background
        ctx.fillStyle = '#1a1a1a';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header with neon effect
        ctx.font = 'bold 120px Arial';
        ctx.textAlign = 'center';
        
        // Neon glow effect
        ctx.shadowColor = '#00ff88';
        ctx.shadowBlur = 20;
        ctx.fillStyle = '#00ff88';
        ctx.fillText('MTLE 2025', this.width/2, 150);
        ctx.shadowBlur = 0;

        // Subject with neon accent
        ctx.font = 'bold 48px Arial';
        ctx.fillStyle = '#00ff88';
        ctx.fillText(`${stats.subject}`, this.width/2, 250);

        // Progress visualization
        this.drawNeonProgressBar(ctx, stats.percentage, 400);

        // Stats with neon accents
        this.drawNeonStats(ctx, stats, 600);

        return canvas.toBuffer('image/png');
    }

    // Design 6: Minimalist Card Layout
    async generateDesign6(stats) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // Soft background
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header
        ctx.font = 'bold 120px Arial';
        ctx.fillStyle = '#212529';
        ctx.textAlign = 'center';
        ctx.fillText('MTLE 2025', this.width/2, 150);

        // Card background
        this.drawCard(ctx, 40, 250, this.width - 80, this.height - 300);

        // Content
        ctx.font = 'bold 48px Arial';
        ctx.fillStyle = '#343a40';
        ctx.fillText(`${stats.subject}`, this.width/2, 350);

        // Progress visualization
        this.drawMinimalistProgress(ctx, stats, 450);

        // Time breakdown
        this.drawTimeBreakdown(ctx, stats, 700);

        return canvas.toBuffer('image/png');
    }

    // Helper methods
    drawProgressCircle(ctx, x, y, radius, percentage) {
        // Background circle
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = '#e9ecef';
        ctx.fill();

        // Progress arc
        ctx.beginPath();
        ctx.arc(x, y, radius, -Math.PI/2, (-Math.PI/2) + (Math.PI * 2 * (percentage/100)));
        ctx.fillStyle = '#4CAF50';
        ctx.fill();

        // Center circle
        ctx.beginPath();
        ctx.arc(x, y, radius * 0.8, 0, Math.PI * 2);
        ctx.fillStyle = '#FFFFFF';
        ctx.fill();

        // Percentage text
        ctx.font = 'bold 64px Arial';
        ctx.fillStyle = '#2C3E50';
        ctx.fillText(`${percentage}%`, x, y + 20);
    }

    drawTimeStats(ctx, stats, y) {
        const items = [
            { icon: '⏱️', label: 'Study Time', value: this.formatTime(stats.actualTime) },
            { icon: '🎯', label: 'Goal', value: this.formatTime(stats.goalTime) },
            { icon: '☕', label: 'Break Time', value: this.formatTime(stats.breakTime) }
        ];

        items.forEach((item, index) => {
            ctx.font = '36px Arial';
            ctx.fillStyle = '#2C3E50';
            ctx.fillText(`${item.icon} ${item.label}: ${item.value}`, 100, y + (index * 60));
        });
    }

    drawNeonProgressBar(ctx, percentage, y) {
        const width = this.width - 200;
        const height = 40;
        const x = 100;

        // Background
        ctx.fillStyle = '#2a2a2a';
        ctx.fillRect(x, y, width, height);

        // Progress
        ctx.shadowColor = '#00ff88';
        ctx.shadowBlur = 20;
        ctx.fillStyle = '#00ff88';
        ctx.fillRect(x, y, width * (percentage/100), height);
        ctx.shadowBlur = 0;

        // Percentage
        ctx.font = 'bold 36px Arial';
        ctx.fillStyle = '#FFFFFF';
        ctx.fillText(`${percentage}%`, this.width/2, y + 80);
    }

    drawNeonStats(ctx, stats, y) {
        const items = [
            { icon: '⏱️', value: this.formatTime(stats.actualTime) },
            { icon: '🎯', value: this.formatTime(stats.goalTime) },
            { icon: '☕', value: this.formatTime(stats.breakTime) }
        ];

        items.forEach((item, index) => {
            const x = 150 + (index * 300);
            ctx.font = '36px Arial';
            ctx.shadowColor = '#00ff88';
            ctx.shadowBlur = 10;
            ctx.fillStyle = '#FFFFFF';
            ctx.fillText(`${item.icon} ${item.value}`, x, y);
            ctx.shadowBlur = 0;
        });
    }

    drawCard(ctx, x, y, width, height) {
        ctx.fillStyle = '#FFFFFF';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.1)';
        ctx.shadowBlur = 20;
        ctx.shadowOffsetY = 10;
        ctx.fillRect(x, y, width, height);
        ctx.shadowBlur = 0;
        ctx.shadowOffsetY = 0;
    }

    drawMinimalistProgress(ctx, stats, y) {
        const width = this.width - 200;
        const height = 8;
        const x = 100;

        // Background
        ctx.fillStyle = '#e9ecef';
        ctx.fillRect(x, y, width, height);

        // Progress
        ctx.fillStyle = '#212529';
        ctx.fillRect(x, y, width * (stats.percentage/100), height);

        // Percentage
        ctx.font = '36px Arial';
        ctx.fillStyle = '#212529';
        ctx.fillText(`${stats.percentage}% Complete`, this.width/2, y + 60);
    }

    drawTimeBreakdown(ctx, stats, y) {
        const timeStats = [
            { label: 'Study Time', value: this.formatTime(stats.actualTime) },
            { label: 'Goal', value: this.formatTime(stats.goalTime) },
            { label: 'Break Time', value: this.formatTime(stats.breakTime) }
        ];

        timeStats.forEach((stat, index) => {
            ctx.font = '32px Arial';
            ctx.fillStyle = '#6c757d';
            ctx.fillText(stat.label, 100, y + (index * 60));
            
            ctx.font = 'bold 32px Arial';
            ctx.fillStyle = '#212529';
            ctx.fillText(stat.value, 400, y + (index * 60));
        });
    }

    formatTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours}:${mins.toString().padStart(2, '0')}`;
    }
}

module.exports = new ImageGenerator();
