const path = require('path');
const MiniCssExtractPlugin = require("mini-css-extract-plugin");
const CopyWebpackPlugin = require('copy-webpack-plugin');

module.exports = {
    mode: 'development',
    devtool: 'inline-source-map',
    entry: [
        './static/js/index.js',
        './static/scss/app.scss'
    ],
    output: {
        path: path.resolve(__dirname, 'public'),
        filename: 'js/main.min.js',
    },
    plugins: [
        new MiniCssExtractPlugin({
            filename: "css/[name].min.css",
            chunkFilename: "css/[id].min.css"
        }),
        new CopyWebpackPlugin({
            patterns: [
                { from:'templates', to: ''},
                { from:'static/img', to:'img'}
            ]
        }), 
    ],
    module: {
        rules: [
            {
                test: /\.s?css$/,
                use: [
                    MiniCssExtractPlugin.loader,
                    "css-loader",
                    "sass-loader"
                ]
            },
            {
                test: /\.js$/,
                exclude: /node_modules/,
                use: []
            },
            {
                test: /\.(png|jpe?g|gif)$/i,
                use: [
                    {
                        loader: 'file-loader?name=/public/img/[name].[ext]',
                    },
                ],
            },
        ],
    }
};